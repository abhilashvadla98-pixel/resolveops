from decimal import Decimal
from enum import Enum

from pydantic import Field, model_validator

from resolveops.models.common import (
    AwareDatetime,
    CurrencyCode,
    DomainModel,
    Identifier,
    NonEmptyText,
    PositiveAmount,
)


class OrderStatus(str, Enum):
    CREATED = "created"
    PAID = "paid"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    PARTIALLY_RETURNED = "partially_returned"
    RETURNED = "returned"
    CANCELLED = "cancelled"


class OrderItem(DomainModel):
    order_item_id: Identifier
    order_id: Identifier
    sku: Identifier
    name: NonEmptyText
    quantity: int = Field(gt=0)
    unit_price: PositiveAmount
    currency: CurrencyCode

    @property
    def subtotal(self) -> Decimal:
        return self.unit_price * self.quantity


class Order(DomainModel):
    order_id: Identifier
    customer_id: Identifier
    status: OrderStatus
    total_amount: PositiveAmount
    currency: CurrencyCode
    items: list[OrderItem] = Field(min_length=1)
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_items(self) -> "Order":
        item_ids: set[str] = set()
        for item in self.items:
            if item.order_item_id in item_ids:
                raise ValueError("order items must have unique IDs")
            if item.order_id != self.order_id:
                raise ValueError("order item belongs to a different order")
            if item.currency != self.currency:
                raise ValueError("order item currency must match the order currency")
            item_ids.add(item.order_item_id)
        return self
