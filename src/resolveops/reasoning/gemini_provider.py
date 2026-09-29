import json

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from resolveops.reasoning.errors import ReasoningProviderError
from resolveops.reasoning.models import ReasoningAssessment, ReasoningContext
from resolveops.reasoning.prompts import SYSTEM_INSTRUCTIONS
from resolveops.reasoning.providers import ModelTokenUsage


class GeminiReasoningProvider:
    def __init__(
        self,
        client: genai.Client,
        *,
        model: str,
        max_input_characters: int = 24_000,
        max_output_tokens: int = 800,
    ) -> None:
        if not model.strip():
            raise ValueError("Gemini model name cannot be empty")
        if max_input_characters < 1_000:
            raise ValueError("Gemini input character limit must be at least 1000")
        if not 100 <= max_output_tokens <= 4_096:
            raise ValueError("Gemini output token limit must be between 100 and 4096")
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
        model: str = "gemini-3.5-flash-lite",
        timeout_seconds: int = 30,
        max_attempts: int = 2,
        max_input_characters: int = 24_000,
        max_output_tokens: int = 800,
    ) -> "GeminiReasoningProvider":
        if not api_key.strip():
            raise ValueError("Gemini API key cannot be empty")
        if not 1 <= timeout_seconds <= 120:
            raise ValueError("Gemini timeout must be between 1 and 120 seconds")
        if not 1 <= max_attempts <= 3:
            raise ValueError("Gemini attempts must be between 1 and 3")
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

    def assess(self, context: ReasoningContext) -> ReasoningAssessment:
        self._last_usage = None
        serialized_context = json.dumps(context.model_dump(mode="json"), sort_keys=True)
        if len(serialized_context) > self._max_input_characters:
            raise ReasoningProviderError(
                "reasoning_input_too_large",
                "The reasoning context exceeds the configured input limit.",
            )
        try:
            response = self.client.models.generate_content(
                model=self._model,
                contents=serialized_context,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTIONS,
                    response_mime_type="application/json",
                    response_json_schema=ReasoningAssessment.model_json_schema(),
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                    candidate_count=1,
                    max_output_tokens=self._max_output_tokens,
                    temperature=0,
                ),
            )
        except (errors.APIError, httpx.HTTPError) as exc:
            raise ReasoningProviderError(
                "reasoning_provider_failed",
                "The reasoning provider request failed.",
            ) from exc
        except (ValidationError, ValueError) as exc:
            raise ReasoningProviderError(
                "reasoning_output_invalid",
                "The reasoning provider returned an invalid structured assessment.",
            ) from exc

        self._last_usage = _token_usage(response.usage_metadata)
        if _was_blocked(response):
            raise ReasoningProviderError(
                "reasoning_provider_refused",
                "The reasoning provider did not return an assessment.",
            )
        try:
            if isinstance(response.parsed, ReasoningAssessment):
                return response.parsed
            if response.parsed is not None:
                return ReasoningAssessment.model_validate(response.parsed)
            if response.text:
                return ReasoningAssessment.model_validate_json(response.text)
        except (ValidationError, ValueError) as exc:
            raise ReasoningProviderError(
                "reasoning_output_invalid",
                "The reasoning provider returned an invalid structured assessment.",
            ) from exc
        raise ReasoningProviderError(
            "reasoning_output_missing",
            "The reasoning provider returned no structured assessment.",
        )


def _token_usage(
    metadata: types.GenerateContentResponseUsageMetadata | None,
) -> ModelTokenUsage | None:
    if metadata is None:
        return None
    input_tokens = int(metadata.prompt_token_count or 0)
    if metadata.total_token_count is not None:
        total_tokens = int(metadata.total_token_count)
        output_tokens = max(total_tokens - input_tokens, 0)
    else:
        output_tokens = int(metadata.candidates_token_count or 0) + int(
            metadata.thoughts_token_count or 0
        )
        total_tokens = input_tokens + output_tokens
    return ModelTokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def _was_blocked(response: types.GenerateContentResponse) -> bool:
    prompt_feedback = response.prompt_feedback
    if prompt_feedback is not None and prompt_feedback.block_reason is not None:
        return True
    blocked_reasons = {"BLOCKLIST", "PROHIBITED_CONTENT", "RECITATION", "SAFETY", "SPII"}
    for candidate in response.candidates or []:
        finish_reason = candidate.finish_reason
        reason_name = getattr(finish_reason, "name", str(finish_reason))
        if reason_name in blocked_reasons:
            return True
    return False
