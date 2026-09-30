from enum import Enum

from pydantic import Field

from resolveops.agents.models import AgentDomain, MultiAgentReasoningResult
from resolveops.models.common import AwareDatetime, DomainModel, Identifier, NonEmptyText


class AgentJobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    RETRYING = "retrying"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


TERMINAL_JOB_STATUSES = frozenset(
    {AgentJobStatus.COMPLETED, AgentJobStatus.FAILED, AgentJobStatus.DEAD_LETTER}
)


class AgentJobEventType(str, Enum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    AGENT_STARTED = "agent_started"
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    RETRY_SCHEDULED = "retry_scheduled"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"


class AgentWorkflowJob(DomainModel):
    job_id: Identifier
    tenant_id: Identifier
    workflow_id: Identifier
    case_id: Identifier
    domain: AgentDomain
    objective: NonEmptyText
    status: AgentJobStatus
    attempts: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    created_at: AwareDatetime
    available_at: AwareDatetime
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    lease_expires_at: AwareDatetime | None = None
    worker_id: Identifier | None = None
    result: MultiAgentReasoningResult | None = None
    error_classification: str | None = None


class AgentJobEvent(DomainModel):
    event_id: int = Field(ge=1)
    job_id: Identifier
    tenant_id: Identifier
    event_type: AgentJobEventType
    status: AgentJobStatus
    occurred_at: AwareDatetime
    details: dict[str, str] = Field(default_factory=dict, max_length=20)


class QueueHealth(DomainModel):
    pending: int = Field(ge=0)
    running: int = Field(ge=0)
    retrying: int = Field(ge=0)
    dead_letter: int = Field(ge=0)
    capacity: int = Field(ge=1)
    accepting: bool


class EnqueueAgentWorkflowRequest(DomainModel):
    workflow_id: Identifier
    case_id: Identifier
    domain: AgentDomain
    objective: NonEmptyText
    idempotency_key: Identifier
