from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from resolveops.database.records import (
    CaseIssuePaymentRecord,
    CaseIssueRecord,
    CaseRecord,
    OrderItemRecord,
    PaymentRecord,
    RefundRecord,
    ReturnItemRecord,
    ReturnRecord,
)
from resolveops.models.case import CaseIssueStatus, CaseIssueType, IssueFinding
from resolveops.models.payment import PaymentStatus
from resolveops.models.refund import RefundKind, RefundStatus
from resolveops.models.returns import ReturnStatus
from resolveops.operations.errors import BusinessRuleError, ResourceNotFoundError
from resolveops.operations.models import IssueRefundRequest
from resolveops.operations.proposals import investigate_issue, same_refund_target


def execute_refund(
    session: Session,
    refund_id: str,
    request: IssueRefundRequest,
    created_at: datetime,
) -> None:
    customer_case = session.get(CaseRecord, request.case_id)
    if customer_case is None:
        raise ResourceNotFoundError("case_not_found", f"case {request.case_id} does not exist")
    issue = session.get(CaseIssueRecord, request.issue_id)
    if issue is None or issue.case_id != request.case_id:
        raise ResourceNotFoundError(
            "issue_not_found", f"issue {request.issue_id} does not belong to the case"
        )
    payment = session.scalar(
        select(PaymentRecord)
        .where(PaymentRecord.payment_id == request.payment_id)
        .with_for_update()
    )
    if payment is None:
        raise ResourceNotFoundError(
            "payment_not_found", f"payment {request.payment_id} does not exist"
        )
    if issue.order_id != customer_case.order_id or payment.order_id != customer_case.order_id:
        raise BusinessRuleError(
            "order_mismatch", "case, issue, and payment must belong to the same order"
        )
    if issue.finding != IssueFinding.CONFIRMED:
        raise BusinessRuleError(
            "issue_not_confirmed", "refunds require a confirmed investigation finding"
        )
    if issue.status != CaseIssueStatus.ACTION_PENDING:
        raise BusinessRuleError("issue_not_actionable", "issue must be in action_pending state")
    if payment.status != PaymentStatus.CAPTURED:
        raise BusinessRuleError(
            "payment_not_captured", "refunds can only be issued against captured payments"
        )
    if payment.currency != request.currency:
        raise BusinessRuleError(
            "currency_mismatch", "refund currency must match the payment currency"
        )

    investigation = investigate_issue(session, request.case_id, request.issue_id)
    if (
        investigation.proposal is None
        or not same_refund_target(investigation.proposal, request)
        or (
            request.idempotency_key.startswith("REFUND-")
            and investigation.proposal.idempotency_key != request.idempotency_key
        )
    ):
        raise BusinessRuleError(
            "proposal_evidence_changed",
            "Fresh authoritative evidence does not support this exact refund; investigate again.",
        )

    if request.kind == RefundKind.DUPLICATE_CHARGE:
        _validate_duplicate_refund(session, issue, payment, request)
    elif request.kind == RefundKind.RETURN:
        _validate_return_refund(session, issue, payment, request)
    else:
        raise BusinessRuleError(
            "unsupported_refund_kind",
            "only confirmed duplicate-charge and return refunds are supported",
        )

    active_statuses = [
        RefundStatus.PENDING,
        RefundStatus.PROCESSING,
        RefundStatus.COMPLETED,
    ]
    existing_amounts = session.scalars(
        select(RefundRecord.amount).where(
            RefundRecord.payment_id == payment.payment_id,
            RefundRecord.status.in_(active_statuses),
        )
    )
    if sum(existing_amounts, Decimal(0)) + request.amount > payment.amount:
        raise BusinessRuleError(
            "payment_refund_limit_exceeded",
            "active refunds plus this refund exceed the captured payment amount",
        )

    session.add(
        RefundRecord(
            refund_id=refund_id,
            payment_id=payment.payment_id,
            order_id=payment.order_id,
            issue_id=issue.issue_id,
            return_id=request.return_id,
            amount=request.amount,
            currency=request.currency,
            status=RefundStatus.PENDING,
            kind=request.kind,
            reason=request.reason,
            created_at=created_at,
            completed_at=None,
        )
    )


def verify_refund(session: Session, refund_id: str, request: IssueRefundRequest) -> bool:
    record = session.get(RefundRecord, refund_id)
    return bool(
        record is not None
        and record.payment_id == request.payment_id
        and record.issue_id == request.issue_id
        and record.return_id == request.return_id
        and record.amount == request.amount
        and record.currency == request.currency
        and record.kind == request.kind
        and record.status
        in {
            RefundStatus.PENDING,
            RefundStatus.PROCESSING,
            RefundStatus.COMPLETED,
        }
    )


def _validate_duplicate_refund(
    session: Session,
    issue: CaseIssueRecord,
    payment: PaymentRecord,
    request: IssueRefundRequest,
) -> None:
    if issue.issue_type != CaseIssueType.DUPLICATE_CHARGE:
        raise BusinessRuleError(
            "issue_type_mismatch", "duplicate-charge refund requires that issue type"
        )
    if request.return_id is not None:
        raise BusinessRuleError(
            "unexpected_return", "duplicate-charge refund cannot reference a return"
        )
    linked_payments = list(
        session.scalars(
            select(PaymentRecord)
            .join(
                CaseIssuePaymentRecord,
                (CaseIssuePaymentRecord.payment_id == PaymentRecord.payment_id)
                & (CaseIssuePaymentRecord.order_id == PaymentRecord.order_id),
            )
            .where(CaseIssuePaymentRecord.issue_id == issue.issue_id)
        )
    )
    if payment.payment_id not in {item.payment_id for item in linked_payments}:
        raise BusinessRuleError(
            "payment_not_in_issue", "payment is not evidence for the duplicate-charge issue"
        )
    matching_captures = [
        item
        for item in linked_payments
        if item.status == PaymentStatus.CAPTURED
        and item.amount == payment.amount
        and item.currency == payment.currency
    ]
    if len({item.payment_id for item in matching_captures}) < 2:
        raise BusinessRuleError(
            "duplicate_evidence_missing",
            "duplicate-charge refund requires two matching captured payments",
        )
    if request.amount != payment.amount:
        raise BusinessRuleError(
            "duplicate_refund_must_be_full",
            "duplicate-charge refund must equal the full captured payment amount",
        )


def _validate_return_refund(
    session: Session,
    issue: CaseIssueRecord,
    payment: PaymentRecord,
    request: IssueRefundRequest,
) -> None:
    if issue.issue_type != CaseIssueType.MISSING_RETURN_REFUND:
        raise BusinessRuleError(
            "issue_type_mismatch", "return refund requires a missing-return-refund issue"
        )
    if request.return_id is None or issue.return_id != request.return_id:
        raise BusinessRuleError(
            "return_mismatch", "refund return must match the return investigated by the issue"
        )
    customer_return = session.scalar(
        select(ReturnRecord).where(ReturnRecord.return_id == request.return_id).with_for_update()
    )
    if customer_return is None or customer_return.order_id != payment.order_id:
        raise ResourceNotFoundError(
            "return_not_found", "return does not exist for the payment order"
        )
    if customer_return.status not in {ReturnStatus.RECEIVED, ReturnStatus.COMPLETED}:
        raise BusinessRuleError(
            "return_not_received", "return must be received before its refund is issued"
        )
    item_rows = session.execute(
        select(
            ReturnItemRecord.quantity,
            OrderItemRecord.unit_price,
            OrderItemRecord.currency,
        )
        .join(
            OrderItemRecord,
            (ReturnItemRecord.order_item_id == OrderItemRecord.order_item_id)
            & (ReturnItemRecord.order_id == OrderItemRecord.order_id),
        )
        .where(ReturnItemRecord.return_id == request.return_id)
    )
    return_value = Decimal(0)
    for quantity, unit_price, currency in item_rows:
        if currency != request.currency:
            raise BusinessRuleError(
                "currency_mismatch", "return item currency must match refund currency"
            )
        return_value += quantity * unit_price

    active_statuses = [
        RefundStatus.PENDING,
        RefundStatus.PROCESSING,
        RefundStatus.COMPLETED,
    ]
    existing_amounts = session.scalars(
        select(RefundRecord.amount).where(
            RefundRecord.return_id == request.return_id,
            RefundRecord.status.in_(active_statuses),
        )
    )
    if sum(existing_amounts, Decimal(0)) + request.amount > return_value:
        raise BusinessRuleError(
            "return_refund_limit_exceeded",
            "active return refunds plus this refund exceed the returned items' value",
        )
