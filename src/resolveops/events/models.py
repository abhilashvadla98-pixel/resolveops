from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from resolveops.models.common import AwareDatetime, DomainModel, Identifier, NonEmptyText
from resolveops.models.refund import RefundStatus


class InboundEventStatus(str, Enum):
    PROCESSED = "processed"
    IGNORED_STALE = "ignored_stale"
    REJECTED = "rejected"


class RefundStatusChangedData(DomainModel):
    refund_id: Identifier
    provider_reference: Identifier
    status: Literal[
        RefundStatus.PROCESSING,
        RefundStatus.COMPLETED,
        RefundStatus.FAILED,
        RefundStatus.CANCELLED,
    ]
    completed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_completion(self) -> "RefundStatusChangedData":
        if self.status == RefundStatus.COMPLETED and self.completed_at is None:
            raise ValueError("completed refund event requires completed_at")
        if self.status != RefundStatus.COMPLETED and self.completed_at is not None:
            raise ValueError("only a completed refund event may include completed_at")
        return self


class RefundStatusChangedEvent(DomainModel):
    event_id: Identifier
    event_type: Literal["refund.status_changed"] = "refund.status_changed"
    source: NonEmptyText
    occurred_at: AwareDatetime
    data: RefundStatusChangedData


class EventReceipt(DomainModel):
    event_id: Identifier
    status: InboundEventStatus
    resource_type: Literal["refund"] = "refund"
    resource_id: Identifier
    idempotent_replay: bool = False
    message: NonEmptyText
    processed_at: AwareDatetime


class WebhookHeaders(DomainModel):
    timestamp: int = Field(gt=0)
    signature: str = Field(pattern=r"^sha256=[a-f0-9]{64}$")
