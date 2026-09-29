from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from resolveops.reasoning.models import ReasoningAssessment, ReasoningContext


class ReasoningProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def assess(self, context: ReasoningContext) -> ReasoningAssessment: ...


@dataclass(frozen=True)
class ModelTokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int

    def __post_init__(self) -> None:
        if min(self.input_tokens, self.output_tokens, self.total_tokens) < 0:
            raise ValueError("model token usage cannot be negative")
        if self.total_tokens < self.input_tokens + self.output_tokens:
            raise ValueError("total token usage cannot be smaller than input plus output")


@runtime_checkable
class UsageReportingReasoningProvider(Protocol):
    @property
    def last_usage(self) -> ModelTokenUsage | None: ...
