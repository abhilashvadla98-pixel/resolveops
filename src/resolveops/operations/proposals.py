"""Authoritative, read-only proposal construction shared by investigation and execution."""

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session

from resolveops.database.records import RefundRecord, ReturnItemRecord, ReturnRecord
from resolveops.database.store import CustomerOperationsStore
from resolveops.domain.billing import find_possible_duplicate_charges
from resolveops.models.case import CaseIssueType, IssueFinding
from resolveops.models.order import OrderStatus
from resolveops.models.payment import PaymentStatus
from resolveops.models.refund import RefundKind, RefundStatus
from resolveops.models.returns import ReturnStatus
from resolveops.operations.models import IssueRefundRequest

ACTIVE = {RefundStatus.PENDING, RefundStatus.PROCESSING, RefundStatus.COMPLETED}


@dataclass(frozen=True)
class Investigation:
    finding: IssueFinding
    evidence: list[tuple[str, str, str]]  # source, reference ID, observed fact
    proposal: IssueRefundRequest | None = None
    existing_refund_id: str | None = None
    error: str | None = None


def investigate_issue(session: Session, case_id: str, issue_id: str) -> Investigation:
    store = CustomerOperationsStore(session)
    case = store.get_case(case_id)
    if case is None:
        raise ValueError("case not found")
    issue = next((item for item in case.issues if item.issue_id == issue_id), None)
    order = store.get_order(case.order_id)
    if issue is None or order is None:
        raise ValueError("issue or order not found")
    payments = store.list_payments(order.order_id)
    captured = [p for p in payments if p.status == PaymentStatus.CAPTURED]
    refunds = list(
        session.scalars(
            select(RefundRecord).where(
                RefundRecord.order_id == order.order_id, RefundRecord.status.in_(ACTIVE)
            )
        )
    )
    evidence = [
        (
            "orders",
            order.order_id,
            f"Order {order.order_id} has a payable total of {order.total_amount} {order.currency}.",
        )
    ]
    evidence.extend(
        (
            "payments",
            p.payment_id,
            (
                f"Payment {p.payment_id}: {p.amount} {p.currency}; {p.status.value}; "
                f"obligation {p.obligation_id or 'unknown'} ({p.obligation_amount}); "
                f"captured {p.captured_at}."
            ),
        )
        for p in payments
    )
    if any(p.currency != order.currency for p in captured):
        return Investigation(
            IssueFinding.UNDETERMINED,
            evidence,
            error="Captured payment currencies conflict with the order; reconcile source records.",
        )

    if issue.issue_type == CaseIssueType.DUPLICATE_CHARGE:
        matches = find_possible_duplicate_charges(payments)
        by_id = {p.payment_id: p for p in payments}
        confirmed = []
        for pair in matches:
            a, b = by_id[pair.first_payment_id], by_id[pair.second_payment_id]
            if (
                a.obligation_id
                and a.obligation_id == b.obligation_id
                and a.obligation_amount == b.obligation_amount == a.amount
                and a.amount == order.total_amount
                and a.currency == order.currency
            ):
                confirmed.append((a, b))
        if not confirmed:
            if (
                sum((p.amount for p in captured if p.currency == order.currency), Decimal(0))
                <= order.total_amount
            ):
                evidence.append(
                    (
                        "orders",
                        order.order_id,
                        "Captured value does not exceed the payable order total; no duplicate refund is justified.",
                    )
                )
                return Investigation(IssueFinding.REJECTED, evidence)
            return Investigation(
                IssueFinding.UNDETERMINED,
                evidence,
                error=(
                    "Payment obligation evidence is missing, conflicting or does not prove duplicate collection. "
                    "An operator must reconcile the captures; equal amounts alone are not sufficient."
                ),
            )
        # This bounded service only handles one extra full capture. Complex allocations require review.
        if len(confirmed) != 1 or len(captured) != 2:
            return Investigation(
                IssueFinding.UNDETERMINED,
                evidence,
                error="Multiple capture allocations require a payment specialist review.",
            )
        a, b = confirmed[0]
        payment = max((a, b), key=lambda p: (p.captured_at, p.payment_id))
        # A duplicate refund against either capture, even in another case, covers this obligation.
        prior = next(
            (
                r
                for r in refunds
                if r.kind == RefundKind.DUPLICATE_CHARGE
                and r.payment_id in {a.payment_id, b.payment_id}
            ),
            None,
        )
        if prior:
            evidence.append(
                (
                    "refunds",
                    prior.refund_id,
                    f"Existing duplicate refund {prior.refund_id} is {prior.status.value}; do not repeat it.",
                )
            )
            return Investigation(
                IssueFinding.CONFIRMED, evidence, existing_refund_id=prior.refund_id
            )
        if any(r.payment_id == payment.payment_id for r in refunds):
            return Investigation(
                IssueFinding.UNDETERMINED,
                evidence,
                error="The extra capture already has refunds; reconcile allocation before another write.",
            )
        amount, kind, return_id = payment.amount, RefundKind.DUPLICATE_CHARGE, None
        reason = f"Verified extra capture of obligation {payment.obligation_id}"
        evidence.append(
            (
                "payments",
                payment.payment_id,
                (
                    f"Two full captures cover the same {payment.obligation_amount} {payment.currency} obligation; "
                    f"the later capture {payment.payment_id} is the bounded refund candidate."
                ),
            )
        )
    elif issue.issue_type in {
        CaseIssueType.MISSING_RETURN_REFUND,
        CaseIssueType.INCORRECT_REFUND_AMOUNT,
    }:
        customer_return = store.get_return(issue.return_id) if issue.return_id else None
        if customer_return is None:
            return Investigation(
                IssueFinding.UNDETERMINED,
                evidence,
                error="Select the returned item/return ID to continue this case.",
            )
        evidence.append(
            (
                "returns",
                customer_return.return_id,
                (
                    f"Return {customer_return.return_id} is {customer_return.status.value}; "
                    f"received at {customer_return.received_at}."
                ),
            )
        )
        if customer_return.status not in {ReturnStatus.RECEIVED, ReturnStatus.COMPLETED}:
            return Investigation(
                IssueFinding.UNDETERMINED,
                evidence,
                error="The return has not been received; warehouse confirmation is required.",
            )
        items = {item.order_item_id: item for item in order.items}
        received_quantities: dict[str, int] = {}
        for returned_id, quantity in session.execute(
            select(ReturnItemRecord.order_item_id, ReturnItemRecord.quantity)
            .join(ReturnRecord, ReturnItemRecord.return_id == ReturnRecord.return_id)
            .where(
                ReturnRecord.order_id == order.order_id,
                ReturnRecord.status.in_([ReturnStatus.RECEIVED, ReturnStatus.COMPLETED]),
            )
        ):
            received_quantities[returned_id] = received_quantities.get(returned_id, 0) + quantity
        if any(
            item_id not in items or quantity > items[item_id].quantity
            for item_id, quantity in received_quantities.items()
        ):
            return Investigation(
                IssueFinding.UNDETERMINED,
                evidence,
                error="Received returns overlap or exceed purchased quantities; review allocation.",
            )
        value = Decimal(0)
        for returned in customer_return.items:
            item = items.get(returned.order_item_id)
            if item is None or returned.quantity > item.quantity or item.currency != order.currency:
                return Investigation(
                    IssueFinding.UNDETERMINED,
                    evidence,
                    error="Return quantities or item currency conflict with the order.",
                )
            value += item.unit_price * returned.quantity
        prior_returns = [r for r in refunds if r.return_id == customer_return.return_id]
        pending = next((r for r in prior_returns if r.status != RefundStatus.COMPLETED), None)
        if pending:
            evidence.append(
                (
                    "refunds",
                    pending.refund_id,
                    f"Existing return refund {pending.refund_id} is {pending.status.value}.",
                )
            )
            return Investigation(
                IssueFinding.CONFIRMED, evidence, existing_refund_id=pending.refund_id
            )
        if issue.issue_type == CaseIssueType.INCORRECT_REFUND_AMOUNT and not prior_returns:
            return Investigation(
                IssueFinding.UNDETERMINED,
                evidence,
                error=(
                    "No completed return refund exists to compare with the expected item value; "
                    "review whether this is a missing-refund complaint instead."
                ),
            )
        amount = value - sum((r.amount for r in prior_returns), Decimal(0))
        if amount <= 0:
            evidence.append(
                (
                    "refunds",
                    prior_returns[-1].refund_id if prior_returns else customer_return.return_id,
                    "Completed return refunds already cover the verified returned-item value.",
                )
            )
            if issue.issue_type == CaseIssueType.INCORRECT_REFUND_AMOUNT:
                return Investigation(IssueFinding.REJECTED, evidence)
            return Investigation(
                IssueFinding.CONFIRMED,
                evidence,
                existing_refund_id=prior_returns[-1].refund_id if prior_returns else None,
            )
        # Only a known full-order capture can be allocated automatically in this bounded domain.
        eligible = [
            p
            for p in captured
            if p.obligation_id
            and p.obligation_amount == p.amount == order.total_amount
            and p.currency == order.currency
        ]
        eligible.sort(key=lambda p: (p.captured_at, p.payment_id))
        return_payment = next(
            (
                p
                for p in eligible
                if p.amount
                - sum((r.amount for r in refunds if r.payment_id == p.payment_id), Decimal(0))
                >= amount
            ),
            None,
        )
        if return_payment is None:
            return Investigation(
                IssueFinding.UNDETERMINED,
                evidence,
                error="No verified capture has sufficient unrefunded value for the returned items.",
            )
        payment = return_payment
        kind, return_id = RefundKind.RETURN, customer_return.return_id
        reason = (
            f"Received items in {return_id}; remaining eligible value {amount} {order.currency}"
        )
        evidence.append(("returns", return_id, reason))
    elif issue.issue_type == CaseIssueType.CANCELLED_ORDER_CHARGE:
        if order.status != OrderStatus.CANCELLED:
            evidence.append(
                (
                    "orders",
                    order.order_id,
                    f"Order status is {order.status.value}, not cancelled; no cancellation refund is justified.",
                )
            )
            return Investigation(IssueFinding.REJECTED, evidence)
        linked_payment_ids = set(issue.payment_ids)
        eligible = [
            payment
            for payment in captured
            if payment.payment_id in linked_payment_ids
            and payment.obligation_id
            and payment.obligation_amount == payment.amount == order.total_amount
            and payment.currency == order.currency
        ]
        if len(eligible) != 1:
            return Investigation(
                IssueFinding.UNDETERMINED,
                evidence,
                error=(
                    "A cancelled-order refund requires exactly one verified full-order capture; "
                    "partial or multiple capture allocations require review."
                ),
            )
        payment = eligible[0]
        payment_refunds = [r for r in refunds if r.payment_id == payment.payment_id]
        pending = next(
            (
                r
                for r in payment_refunds
                if r.status in {RefundStatus.PENDING, RefundStatus.PROCESSING}
            ),
            None,
        )
        if pending is not None:
            evidence.append(
                (
                    "refunds",
                    pending.refund_id,
                    f"Existing cancellation refund {pending.refund_id} is {pending.status.value}.",
                )
            )
            return Investigation(
                IssueFinding.CONFIRMED, evidence, existing_refund_id=pending.refund_id
            )
        completed_amount = sum(
            (r.amount for r in payment_refunds if r.status == RefundStatus.COMPLETED),
            Decimal(0),
        )
        amount = payment.amount - completed_amount
        if amount <= 0:
            evidence.append(
                (
                    "refunds",
                    payment_refunds[-1].refund_id if payment_refunds else payment.payment_id,
                    "Completed refunds already cover the cancelled order charge.",
                )
            )
            return Investigation(IssueFinding.REJECTED, evidence)
        kind, return_id = RefundKind.CANCELLED_ORDER, None
        reason = (
            f"Cancelled order {order.order_id}; remaining captured value {amount} {order.currency}"
        )
        evidence.append(
            (
                "orders",
                order.order_id,
                f"Order is cancelled and payment {payment.payment_id} remains captured; {amount} {order.currency} is refundable.",
            )
        )
    else:
        return Investigation(IssueFinding.UNDETERMINED, evidence, error="Unsupported issue type.")

    identity = f"{payment.payment_id}|{kind.value}|{return_id}|{amount}|{payment.currency}"
    failed_attempts = list(
        session.scalars(
            select(RefundRecord)
            .where(
                RefundRecord.payment_id == payment.payment_id,
                RefundRecord.kind == kind,
                RefundRecord.return_id == return_id,
                RefundRecord.currency == payment.currency,
                RefundRecord.status.in_([RefundStatus.FAILED, RefundStatus.CANCELLED]),
            )
            .order_by(RefundRecord.refund_id)
        )
    )
    if failed_attempts:
        # A new, separately approved attempt follows authoritative terminal failures.
        # Retries of that attempt retain the same key; pending/unknown never reach here.
        identity += "|recovery:" + ",".join(r.refund_id for r in failed_attempts)
        evidence.extend(
            (
                "refunds",
                prior.refund_id,
                f"Previous refund {prior.refund_id} is {prior.status.value}; a replacement needs fresh approval.",
            )
            for prior in failed_attempts
        )
    proposal = IssueRefundRequest(
        idempotency_key="REFUND-" + sha256(identity.encode()).hexdigest()[:40],
        case_id=case_id,
        issue_id=issue_id,
        payment_id=payment.payment_id,
        amount=amount,
        currency=payment.currency,
        kind=kind,
        return_id=return_id,
        reason=reason,
    )
    return Investigation(IssueFinding.CONFIRMED, evidence, proposal=proposal)


def same_refund_target(left: IssueRefundRequest, right: IssueRefundRequest) -> bool:
    fields = ("case_id", "issue_id", "payment_id", "amount", "currency", "kind", "return_id")
    return all(getattr(left, field) == getattr(right, field) for field in fields)
