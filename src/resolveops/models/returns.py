from enum import Enum

from pydantic import Field, model_validator

from resolveops.models.common import (
    AwareDatetime,
    DomainModel,
    Identifier,
    NonEmptyText,
)


class ReturnStatus(str, Enum):
    REQUESTED = "requested"
    AUTHORIZED = "authorized"
    IN_TRANSIT = "in_transit"
    RECEIVED = "received"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ReturnItem(DomainModel):
    order_item_id: Identifier
    quantity: int = Field(gt=0)
    reason: NonEmptyText


class Return(DomainModel):
    return_id: Identifier
    order_id: Identifier
    customer_id: Identifier
    status: ReturnStatus
    items: list[ReturnItem] = Field(min_length=1)
    refund_ids: list[Identifier] = Field(default_factory=list)
    created_at: AwareDatetime
    received_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_return(self) -> "Return":
        item_ids = [item.order_item_id for item in self.items]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("return items must have unique order item IDs")
        if len(self.refund_ids) != len(set(self.refund_ids)):
            raise ValueError("return refund IDs must be unique")
        if (
            self.status in {ReturnStatus.RECEIVED, ReturnStatus.COMPLETED}
            and self.received_at is None
        ):
            raise ValueError("received and completed returns require received_at")
        if self.received_at is not None and self.received_at < self.created_at:
            raise ValueError("received_at cannot be earlier than created_at")
        return self
