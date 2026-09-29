from enum import Enum

from pydantic import model_validator

from resolveops.models.common import (
    AwareDatetime,
    CurrencyCode,
    DomainModel,
    Identifier,
    PositiveAmount,
)


class PaymentStatus(str, Enum):
    PENDING = "pending"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"
    VOIDED = "voided"


class Payment(DomainModel):
    payment_id: Identifier
    order_id: Identifier
    amount: PositiveAmount
    currency: CurrencyCode
    status: PaymentStatus
    created_at: AwareDatetime
    captured_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_capture(self) -> "Payment":
        if self.status == PaymentStatus.CAPTURED and self.captured_at is None:
            raise ValueError("captured payments require captured_at")
        if self.captured_at is not None and self.captured_at < self.created_at:
            raise ValueError("captured_at cannot be earlier than created_at")
        return self
