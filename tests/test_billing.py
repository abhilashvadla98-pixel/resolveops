from resolveops.domain.billing import has_possible_duplicate_charge
from resolveops.models.payment import Payment


def test_detects_possible_duplicate_charge() -> None:
    payment_one = Payment(
        payment_id="PAY-1001",
        order_id="ORD-48391",
        amount="1499.00",
        currency="USD",
        status="succeeded",
        created_at="2026-09-01T10:01:00",
    )

    payment_two = Payment(
        payment_id="PAY-1002",
        order_id="ORD-48391",
        amount="1499.00",
        currency="USD",
        status="succeeded",
        created_at="2026-09-01T10:02:00",
    )

    assert has_possible_duplicate_charge([payment_one, payment_two]) is True


def test_does_not_flag_different_amounts() -> None:
    payment_one = Payment(
        payment_id="PAY-1001",
        order_id="ORD-48391",
        amount="1499.00",
        currency="USD",
        status="succeeded",
        created_at="2026-09-01T10:01:00",
    )

    payment_two = Payment(
        payment_id="PAY-1002",
        order_id="ORD-48391",
        amount="499.00",
        currency="USD",
        status="succeeded",
        created_at="2026-09-01T10:02:00",
    )

    assert has_possible_duplicate_charge([payment_one, payment_two]) is False