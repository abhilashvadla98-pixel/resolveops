from datetime import timedelta

import pytest

from resolveops.domain.billing import (
    find_possible_duplicate_charges,
    has_possible_duplicate_charge,
)
from resolveops.models.payment import Payment


def payment(
    payment_id: str,
    *,
    amount: str = "1499.00",
    order_id: str = "ORD-48391",
    currency: str = "USD",
    status: str = "captured",
    captured_at: str | None = "2026-09-01T10:01:00Z",
) -> Payment:
    return Payment(
        payment_id=payment_id,
        order_id=order_id,
        amount=amount,
        currency=currency,
        status=status,
        created_at="2026-09-01T10:00:00Z",
        captured_at=captured_at,
    )


def test_detects_possible_duplicate_charge_and_returns_evidence() -> None:
    payment_one = payment("PAY-1001")
    payment_two = payment("PAY-1002", captured_at="2026-09-01T10:02:00Z")

    matches = find_possible_duplicate_charges([payment_one, payment_two])

    assert has_possible_duplicate_charge([payment_one, payment_two]) is True
    assert len(matches) == 1
    assert matches[0].first_payment_id == "PAY-1001"
    assert matches[0].second_payment_id == "PAY-1002"
    assert matches[0].time_apart == timedelta(minutes=1)


def test_does_not_flag_different_amounts() -> None:
    payment_one = payment("PAY-1001")
    payment_two = payment("PAY-1002", amount="499.00")

    assert has_possible_duplicate_charge([payment_one, payment_two]) is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"order_id": "ORD-OTHER"},
        {"currency": "EUR"},
        {"status": "authorized", "captured_at": None},
    ],
)
def test_does_not_flag_payments_with_different_context(overrides: dict[str, str | None]) -> None:
    payment_one = payment("PAY-1001")
    payment_two = payment("PAY-1002", **overrides)

    assert has_possible_duplicate_charge([payment_one, payment_two]) is False


def test_same_payment_record_is_not_a_duplicate() -> None:
    payment_one = payment("PAY-1001")
    repeated_record = payment("PAY-1001", captured_at="2026-09-01T10:02:00Z")

    assert has_possible_duplicate_charge([payment_one, repeated_record]) is False


def test_does_not_flag_matching_payments_outside_the_time_window() -> None:
    payment_one = payment("PAY-1001")
    payment_two = payment("PAY-1002", captured_at="2026-09-03T10:01:00Z")

    assert has_possible_duplicate_charge([payment_one, payment_two]) is False


def test_rejects_non_positive_duplicate_window() -> None:
    with pytest.raises(ValueError, match="max_time_apart must be positive"):
        find_possible_duplicate_charges([], max_time_apart=timedelta(0))
