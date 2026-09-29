import json

from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from resolveops.reasoning.errors import ReasoningProviderError
from resolveops.reasoning.models import ReasoningAssessment, ReasoningContext
from resolveops.reasoning.prompts import SYSTEM_INSTRUCTIONS
from resolveops.reasoning.providers import ModelTokenUsage


class OpenAIReasoningProvider:
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

    def assess(self, context: ReasoningContext) -> ReasoningAssessment:
        self._last_usage = None
        try:
            response = self.client.responses.parse(
                model=self._model,
                instructions=SYSTEM_INSTRUCTIONS,
                input=json.dumps(context.model_dump(mode="json"), sort_keys=True),
                text_format=ReasoningAssessment,
                store=False,
            )
        except OpenAIError as exc:
            raise ReasoningProviderError(
                "reasoning_provider_failed",
                "The reasoning provider request failed.",
            ) from exc
        except ValidationError as exc:
            raise ReasoningProviderError(
                "reasoning_output_invalid",
                "The reasoning provider returned an invalid structured assessment.",
            ) from exc
        parsed = response.output_parsed
        if hasattr(response, "usage") and response.usage is not None:
            self._last_usage = ModelTokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                total_tokens=response.usage.total_tokens,
            )
        if parsed is None:
            raise ReasoningProviderError(
                "reasoning_output_missing",
                "The reasoning provider returned no structured assessment.",
            )
        return parsed
