from datetime import datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel


class RefundStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Refund(BaseModel):
    refund_id: str
    payment_id: str
    order_id: str
    amount: Decimal
    currency: str
    status: RefundStatus
    reason: str
    created_at: datetime