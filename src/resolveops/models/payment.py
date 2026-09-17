from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel


class PaymentStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


class Payment(BaseModel):
    payment_id: str
    order_id: str
    amount: Decimal
    currency: str
    status: PaymentStatus
    created_at: datetime