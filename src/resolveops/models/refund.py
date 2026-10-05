from enum import Enum

from pydantic import model_validator

from resolveops.models.common import (
    AwareDatetime,
    CurrencyCode,
    DomainModel,
    Identifier,
    NonEmptyText,
    PositiveAmount,
)


class RefundStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RefundKind(str, Enum):
    DUPLICATE_CHARGE = "duplicate_charge"
    RETURN = "return"
    CANCELLED_ORDER = "cancelled_order"
    GOODWILL = "goodwill"
    OTHER = "other"


class Refund(DomainModel):
    refund_id: Identifier
    payment_id: Identifier
    order_id: Identifier
    issue_id: Identifier
    return_id: Identifier | None = None
    amount: PositiveAmount
    currency: CurrencyCode
    status: RefundStatus
    kind: RefundKind
    reason: NonEmptyText
    created_at: AwareDatetime
    completed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_refund_context(self) -> "Refund":
        if self.kind == RefundKind.RETURN and self.return_id is None:
            raise ValueError("return refunds require return_id")
        if (
            self.kind
            in {
                RefundKind.DUPLICATE_CHARGE,
                RefundKind.CANCELLED_ORDER,
            }
            and self.return_id is not None
        ):
            raise ValueError("non-return refunds cannot reference a return")
        if self.status == RefundStatus.COMPLETED and self.completed_at is None:
            raise ValueError("completed refunds require completed_at")
        if self.completed_at is not None and self.completed_at < self.created_at:
            raise ValueError("completed_at cannot be earlier than created_at")
        return self
