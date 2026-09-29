from enum import Enum
from math import isfinite

from pydantic import Field, model_validator

from resolveops.models.common import AwareDatetime, DomainModel, Identifier, NonEmptyText

TraceAttribute = str | int | float | bool | None


class TraceComponent(str, Enum):
    API = "api"
    WORKFLOW = "workflow"
    WORKFLOW_NODE = "workflow_node"
    TOOL = "tool"
    RETRIEVAL = "retrieval"
    LLM = "llm"


class TraceStatus(str, Enum):
    OK = "ok"
    ERROR = "error"


class TraceEvent(DomainModel):
    trace_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    span_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    parent_span_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{16}$")
    component: TraceComponent
    operation: Identifier
    status: TraceStatus
    started_at: AwareDatetime
    duration_ms: float = Field(ge=0)
    workflow_id: Identifier | None = None
    case_id: Identifier | None = None
    attributes: dict[str, TraceAttribute] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_numbers(self) -> "TraceEvent":
        if not isfinite(self.duration_ms):
            raise ValueError("trace duration must be finite")
        if any(
            isinstance(value, float) and not isfinite(value) for value in self.attributes.values()
        ):
            raise ValueError("numeric trace attributes must be finite")
        return self


class LatencyDistribution(DomainModel):
    sample_count: int = Field(gt=0)
    minimum_ms: float = Field(ge=0)
    p50_ms: float = Field(ge=0)
    p95_ms: float = Field(ge=0)
    maximum_ms: float = Field(ge=0)


class OperationMetrics(DomainModel):
    component: TraceComponent
    operation: Identifier
    call_count: int = Field(gt=0)
    failure_count: int = Field(ge=0)
    latency: LatencyDistribution


class ObservabilitySummary(DomainModel):
    trace_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    workflow_count: int = Field(ge=0)
    workflow_outcomes: dict[str, int]
    operations: list[OperationMetrics]
    retry_scheduled_count: int = Field(ge=0)
    total_input_tokens: int | None = Field(default=None, ge=0)
    total_output_tokens: int | None = Field(default=None, ge=0)
    total_cost_usd: float | None = Field(default=None, ge=0)


class PerformanceReport(DomainModel):
    measured_at: AwareDatetime
    environment: dict[str, str]
    dataset_name: NonEmptyText
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    warmup_runs: int = Field(ge=0)
    measured_runs: int = Field(gt=0)
    cases_per_run: int = Field(gt=0)
    evaluation_passed_count: int = Field(ge=0)
    evaluation_failed_count: int = Field(ge=0)
    metrics: ObservabilitySummary
    measurement_notes: list[NonEmptyText]
