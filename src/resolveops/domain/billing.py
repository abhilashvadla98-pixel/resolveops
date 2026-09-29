from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from resolveops.models.payment import Payment, PaymentStatus

DEFAULT_DUPLICATE_WINDOW = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class DuplicateChargeMatch:
    first_payment_id: str
    second_payment_id: str
    order_id: str
    amount: Decimal
    currency: str
    first_captured_at: datetime
    second_captured_at: datetime

    @property
    def time_apart(self) -> timedelta:
        return abs(self.second_captured_at - self.first_captured_at)


def find_possible_duplicate_charges(
    payments: list[Payment],
    *,
    max_time_apart: timedelta = DEFAULT_DUPLICATE_WINDOW,
) -> list[DuplicateChargeMatch]:
    if max_time_apart <= timedelta(0):
        raise ValueError("max_time_apart must be positive")

    captured_payments = [
        (payment, payment.captured_at)
        for payment in payments
        if payment.status == PaymentStatus.CAPTURED and payment.captured_at is not None
    ]
    matches: list[DuplicateChargeMatch] = []

    for index, (payment, captured_at) in enumerate(captured_payments):
        for other_payment, other_captured_at in captured_payments[index + 1 :]:
            if (
                payment.payment_id != other_payment.payment_id
                and payment.order_id == other_payment.order_id
                and payment.amount == other_payment.amount
                and payment.currency == other_payment.currency
                and abs(captured_at - other_captured_at) <= max_time_apart
            ):
                matches.append(
                    DuplicateChargeMatch(
                        first_payment_id=payment.payment_id,
                        second_payment_id=other_payment.payment_id,
                        order_id=payment.order_id,
                        amount=payment.amount,
                        currency=payment.currency,
                        first_captured_at=captured_at,
                        second_captured_at=other_captured_at,
                    )
                )

    return matches


def has_possible_duplicate_charge(
    payments: list[Payment],
    *,
    max_time_apart: timedelta = DEFAULT_DUPLICATE_WINDOW,
) -> bool:
    return bool(
        find_possible_duplicate_charges(
            payments,
            max_time_apart=max_time_apart,
        )
    )
