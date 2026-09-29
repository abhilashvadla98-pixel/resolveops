import pytest
from pydantic import ValidationError

from resolveops.models.customer import Customer
from resolveops.models.order import Order, OrderItem
from resolveops.models.payment import Payment
from resolveops.models.refund import Refund
from resolveops.models.returns import Return, ReturnItem

OPENED_AT = "2026-09-01T09:00:00Z"
UPDATED_AT = "2026-09-01T10:00:00Z"


def order_item(**overrides: object) -> OrderItem:
    values: dict[str, object] = {
        "order_item_id": "ITEM-1001",
        "order_id": "ORD-48391",
        "sku": "SKU-COFFEE-01",
        "name": "Espresso machine",
        "quantity": 1,
        "unit_price": "1499.00",
        "currency": "USD",
    }
    values.update(overrides)
    return OrderItem(**values)


def test_customer_requires_valid_non_empty_identity() -> None:
    customer = Customer(
        customer_id="CUST-1001",
        name="Maya Patel",
        email="maya.patel@example.com",
        tier="gold",
        status="active",
    )

    assert customer.customer_id == "CUST-1001"

    with pytest.raises(ValidationError):
        Customer(
            customer_id=" ",
            name="Maya Patel",
            email="maya.patel@example.com",
            tier="gold",
            status="active",
        )


def test_order_checks_item_relationship_and_currency() -> None:
    order = Order(
        order_id="ORD-48391",
        customer_id="CUST-1001",
        status="delivered",
        total_amount="1499.00",
        currency="USD",
        items=[order_item()],
        created_at=OPENED_AT,
    )

    assert order.items[0].subtotal == order.total_amount

    with pytest.raises(ValidationError, match="different order"):
        Order(
            order_id="ORD-48391",
            customer_id="CUST-1001",
            status="delivered",
            total_amount="1499.00",
            currency="USD",
            items=[order_item(order_id="ORD-OTHER")],
            created_at=OPENED_AT,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount", "-1.00"),
        ("currency", "usd"),
        ("created_at", "2026-09-01T09:00:00"),
    ],
)
def test_payment_rejects_invalid_financial_data(field: str, value: str) -> None:
    values = {
        "payment_id": "PAY-1001",
        "order_id": "ORD-48391",
        "amount": "1499.00",
        "currency": "USD",
        "status": "captured",
        "created_at": OPENED_AT,
        "captured_at": UPDATED_AT,
    }
    values[field] = value

    with pytest.raises(ValidationError):
        Payment(**values)


def test_captured_payment_requires_capture_time() -> None:
    with pytest.raises(ValidationError, match="captured_at"):
        Payment(
            payment_id="PAY-1001",
            order_id="ORD-48391",
            amount="1499.00",
            currency="USD",
            status="captured",
            created_at=OPENED_AT,
        )


def test_return_tracks_items_independently_from_order_status() -> None:
    customer_return = Return(
        return_id="RET-3001",
        order_id="ORD-48391",
        customer_id="CUST-1001",
        status="received",
        items=[
            ReturnItem(
                order_item_id="ITEM-1001",
                quantity=1,
                reason="Arrived damaged",
            )
        ],
        created_at=OPENED_AT,
        received_at=UPDATED_AT,
    )

    assert customer_return.items[0].order_item_id == "ITEM-1001"

    with pytest.raises(ValidationError, match="received_at"):
        Return(
            return_id="RET-3001",
            order_id="ORD-48391",
            customer_id="CUST-1001",
            status="received",
            items=[ReturnItem(order_item_id="ITEM-1001", quantity=1, reason="Damaged")],
            created_at=OPENED_AT,
        )


def test_refund_kind_keeps_return_and_duplicate_refunds_distinct() -> None:
    return_refund = Refund(
        refund_id="REF-2001",
        payment_id="PAY-1001",
        order_id="ORD-48391",
        issue_id="ISSUE-2",
        return_id="RET-3001",
        amount="499.00",
        currency="USD",
        status="completed",
        kind="return",
        reason="Refund for returned order item",
        created_at=OPENED_AT,
        completed_at=UPDATED_AT,
    )

    assert return_refund.return_id == "RET-3001"

    with pytest.raises(ValidationError, match="cannot reference a return"):
        Refund(
            refund_id="REF-2002",
            payment_id="PAY-1002",
            order_id="ORD-48391",
            issue_id="ISSUE-1",
            return_id="RET-3001",
            amount="1499.00",
            currency="USD",
            status="pending",
            kind="duplicate_charge",
            reason="Duplicate capture",
            created_at=OPENED_AT,
        )
