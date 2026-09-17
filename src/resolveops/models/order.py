from datetime import datetime
from enum import Enum
from decimal import Decimal

from pydantic import BaseModel


class OrderStatus(str, Enum):
    CREATED = "created"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    RETURNED = "returned"
    CANCELLED = "cancelled"


class Order(BaseModel):
    order_id: str
    customer_id: str
    status: OrderStatus
    total_amount: Decimal
    currency: str
    created_at: datetime