import json
from typing import Protocol, TypeVar, runtime_checkable

import httpx
from google import genai
from google.genai import errors, types
from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ValidationError

from resolveops.reasoning.errors import ReasoningProviderError
from resolveops.reasoning.providers import ModelTokenUsage

OutputT = TypeVar("OutputT", bound=BaseModel)


class StructuredAgentProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def invoke(
        self,
        *,
        instructions: str,
        context: BaseModel | dict[str, object],
        response_model: type[OutputT],
    ) -> OutputT: ...


@runtime_checkable
class UsageReportingAgentProvider(Protocol):
    @property
    def last_usage(self) -> ModelTokenUsage | None: ...


class GeminiStructuredAgentProvider:
    def __init__(
        self,
        client: genai.Client,
        *,
        model: str,
        max_input_characters: int = 16_000,
        max_output_tokens: int = 600,
    ) -> None:
        if not model.strip():
            raise ValueError("Gemini model name cannot be empty")
        self.client = client
        self._model = model
        self._max_input_characters = max_input_characters
        self._max_output_tokens = max_output_tokens
        self._last_usage: ModelTokenUsage | None = None

    @classmethod
    def from_api_key(
        cls,
        api_key: str,
        *,
        model: str,
        timeout_seconds: int = 30,
        max_attempts: int = 2,
        max_input_characters: int = 16_000,
        max_output_tokens: int = 600,
    ) -> "GeminiStructuredAgentProvider":
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=timeout_seconds * 1_000,
                retry_options=types.HttpRetryOptions(attempts=max_attempts),
            ),
        )
        return cls(
            client,
            model=model,
            max_input_characters=max_input_characters,
            max_output_tokens=max_output_tokens,
        )

    @property
    def provider_name(self) -> str:
        return "gemini"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def last_usage(self) -> ModelTokenUsage | None:
        return self._last_usage

    def invoke(
        self,
        *,
        instructions: str,
        context: BaseModel | dict[str, object],
        response_model: type[OutputT],
    ) -> OutputT:
        self._last_usage = None
        payload = _context_json(context)
        if len(payload) > self._max_input_characters:
            raise ReasoningProviderError(
                "agent_context_too_large", "The agent context exceeds its configured input limit."
            )
        try:
            response = self.client.models.generate_content(
                model=self._model,
                contents=payload,
                config=types.GenerateContentConfig(
                    system_instruction=instructions,
                    response_mime_type="application/json",
                    response_json_schema=_gemini_response_schema(response_model),
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    candidate_count=1,
                    max_output_tokens=self._max_output_tokens,
                    temperature=0,
                    thinking_config=(
                        None
                        if "flash-lite" in self._model
                        else types.ThinkingConfig(thinking_budget=0)
                    ),
                ),
            )
        except (errors.APIError, httpx.HTTPError) as exc:
            raise ReasoningProviderError(
                _provider_error_code(exc), "The agent provider request failed."
            ) from exc
        self._last_usage = _gemini_usage(response.usage_metadata)
        if any(
            str(candidate.finish_reason).endswith("MAX_TOKENS")
            for candidate in (getattr(response, "candidates", None) or [])
        ):
            raise ReasoningProviderError(
                "agent_output_token_limit",
                "The provider reached its configured output-token limit before completing the structured response.",
            )
        try:
            if isinstance(response.parsed, response_model):
                return response.parsed
            if response.parsed is not None:
                return response_model.model_validate(response.parsed)
            if response.text:
                return response_model.model_validate_json(response.text)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}:{error['type']}:{error['msg']}"
                for error in exc.errors(include_input=False)[:5]
            )
            raise ReasoningProviderError(
                "agent_output_invalid",
                f"The agent provider returned invalid structured output ({problems}).",
            ) from exc
        except ValueError as exc:
            raise ReasoningProviderError(
                "agent_output_invalid", "The agent provider returned invalid structured output."
            ) from exc
        raise ReasoningProviderError(
            "agent_output_missing", "The agent provider returned no structured output."
        )


class OpenAIStructuredAgentProvider:
    def __init__(self, client: OpenAI, *, model: str) -> None:
        if not model.strip():
            raise ValueError("OpenAI model name cannot be empty")
        self.client = client
        self._model = model
        self._last_usage: ModelTokenUsage | None = None

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def last_usage(self) -> ModelTokenUsage | None:
        return self._last_usage

    def invoke(
        self,
        *,
        instructions: str,
        context: BaseModel | dict[str, object],
        response_model: type[OutputT],
    ) -> OutputT:
        self._last_usage = None
        try:
            response = self.client.responses.parse(
                model=self._model,
                instructions=instructions,
                input=_context_json(context),
                text_format=response_model,
                store=False,
            )
        except OpenAIError as exc:
            raise ReasoningProviderError(
                "agent_provider_failed", "The agent provider request failed."
            ) from exc
        if response.usage is not None:
            self._last_usage = ModelTokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                total_tokens=response.usage.total_tokens,
            )
        if response.output_parsed is None:
            raise ReasoningProviderError(
                "agent_output_missing", "The agent provider returned no structured output."
            )
        return response.output_parsed


def _context_json(context: BaseModel | dict[str, object]) -> str:
    value = context.model_dump(mode="json") if isinstance(context, BaseModel) else context
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _provider_error_code(exc: Exception) -> str:
    status = getattr(exc, "status_code", getattr(exc, "code", None))
    if not isinstance(status, int):
        return "agent_provider_failed"
    if status >= 500:
        return "agent_provider_unavailable"
    return {
        400: "agent_provider_invalid_request",
        401: "agent_provider_auth_failed",
        403: "agent_provider_denied",
        404: "agent_model_unavailable",
        429: "agent_provider_rate_limited",
    }.get(status, "agent_provider_failed")


def _gemini_response_schema(response_model: type[BaseModel]) -> dict[str, object]:
    """Return the JSON Schema subset accepted by Gemini generateContent.

    Pydantic emits validation-only keywords that remain enforced when we validate the
    response locally, but some Gemini model endpoints reject those keywords at request time.
    """
    raw = response_model.model_json_schema()
    definitions = raw.get("$defs", {})
    unsupported = {
        "$defs",
        "additionalProperties",
        "default",
        "description",
        "maxItems",
        "maxLength",
        "maximum",
        "minItems",
        "minLength",
        "minimum",
        "pattern",
        "title",
    }

    def clean(value: object) -> object:
        if isinstance(value, dict):
            reference = value.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/$defs/"):
                definition = definitions.get(reference.rsplit("/", 1)[-1])
                if definition is None:
                    raise ValueError(f"Unknown local schema reference: {reference}")
                return clean(definition)
            return {key: clean(item) for key, item in value.items() if key not in unsupported}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return clean(raw)  # type: ignore[return-value]


def _gemini_usage(
    metadata: types.GenerateContentResponseUsageMetadata | None,
) -> ModelTokenUsage | None:
    if metadata is None:
        return None
    input_tokens = int(metadata.prompt_token_count or 0)
    total_tokens = int(metadata.total_token_count or 0)
    output_tokens = max(total_tokens - input_tokens, 0)
    return ModelTokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=max(total_tokens, input_tokens + output_tokens),
    )
