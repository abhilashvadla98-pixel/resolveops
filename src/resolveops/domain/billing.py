from resolveops.models.payment import Payment, PaymentStatus


def has_possible_duplicate_charge(payments: list[Payment]) -> bool:
    successful_payments = [
        payment
        for payment in payments
        if payment.status == PaymentStatus.SUCCEEDED
    ]

    for index, payment in enumerate(successful_payments):
        for other_payment in successful_payments[index + 1:]:
            if (
                payment.order_id == other_payment.order_id
                and payment.amount == other_payment.amount
                and payment.currency == other_payment.currency
            ):
                return True

    return False