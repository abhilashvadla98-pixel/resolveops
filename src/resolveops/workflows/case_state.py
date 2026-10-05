from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from resolveops.database.records import (
    CaseIssueActionRecord,
    CaseIssueEvidenceRecord,
    CaseIssueRecord,
    CaseIssueResolutionRecord,
    CaseIssueVerificationRecord,
    CaseRecord,
    OrderItemRecord,
    OrderRecord,
    PaymentRecord,
    RefundRecord,
    ReturnItemRecord,
)
from resolveops.database.workflow_records import WorkflowRunRecord
from resolveops.models.case import (
    CaseIssueStatus,
    CaseIssueType,
    CaseStatus,
    IssueActionStatus,
    IssueFinding,
    VerificationStatus,
)
from resolveops.models.refund import RefundKind, RefundStatus
from resolveops.responses.customer import CustomerResponseComposer
from resolveops.workflows.models import (
    WorkflowLifecycleStatus,
    WorkflowOutcome,
    WorkflowPause,
    WorkflowResult,
    WorkflowStatus,
)

PENDING_REFUND_STATUSES = {RefundStatus.PENDING, RefundStatus.PROCESSING}
REFUND_OUTCOMES = {
    WorkflowOutcome.ACTION_VERIFIED,
    WorkflowOutcome.REFUND_SUBMITTED,
    WorkflowOutcome.REFUND_SETTLED,
    WorkflowOutcome.WAITING_EXTERNAL,
}
REFUND_REVIEW_ERRORS = {"refund_failed", "refund_cancelled", "refund_settlement_incomplete"}


@dataclass(frozen=True)
class RefundStateProjection:
    status: WorkflowStatus
    outcome: WorkflowOutcome
    summary: str
    error_code: str | None = None


def refund_state_projection(session: Session, refund: RefundRecord) -> RefundStateProjection:
    """Evaluate settlement from stored provider records, never from a graph checkpoint."""
    if refund.status in {RefundStatus.FAILED, RefundStatus.CANCELLED}:
        return RefundStateProjection(
            WorkflowStatus.ESCALATED,
            WorkflowOutcome.NEEDS_REVIEW,
            f"The provider reports refund {refund.refund_id} as {refund.status.value}. "
            "An operator must review the provider result before requesting a replacement refund.",
            f"refund_{refund.status.value}",
        )
    if refund.kind in {RefundKind.DUPLICATE_CHARGE, RefundKind.CANCELLED_ORDER}:
        payment = session.get(PaymentRecord, refund.payment_id)
        required = (
            payment.amount if payment is not None and payment.currency == refund.currency else None
        )
        related = select(RefundRecord).where(
            RefundRecord.payment_id == refund.payment_id,
            RefundRecord.kind == refund.kind,
            RefundRecord.currency == refund.currency,
        )
    elif refund.kind == RefundKind.RETURN:
        returned_items = session.execute(
            select(ReturnItemRecord, OrderItemRecord)
            .join(OrderItemRecord, ReturnItemRecord.order_item_id == OrderItemRecord.order_item_id)
            .where(ReturnItemRecord.return_id == refund.return_id)
        ).all()
        required = (
            sum(
                (item.quantity * order_item.unit_price for item, order_item in returned_items),
                Decimal(0),
            )
            if returned_items
            and all(order_item.currency == refund.currency for _, order_item in returned_items)
            else None
        )
        related = select(RefundRecord).where(
            RefundRecord.return_id == refund.return_id,
            RefundRecord.kind == refund.kind,
            RefundRecord.currency == refund.currency,
        )
    else:
        required = None
        related = select(RefundRecord).where(RefundRecord.refund_id == refund.refund_id)
    refunds = list(session.scalars(related))
    pending = [item for item in refunds if item.status in PENDING_REFUND_STATUSES]
    if pending:
        return RefundStateProjection(
            WorkflowStatus.WAITING_EXTERNAL,
            WorkflowOutcome.WAITING_EXTERNAL,
            "Refund submission is recorded; settlement is still pending for "
            + ", ".join(sorted(item.refund_id for item in pending))
            + ". The issue remains open until final provider verification.",
        )
    settled = sum(
        (item.amount for item in refunds if item.status == RefundStatus.COMPLETED), Decimal(0)
    )
    if required is not None and settled == required:
        return RefundStateProjection(
            WorkflowStatus.COMPLETED,
            WorkflowOutcome.REFUND_SETTLED,
            f"Fresh provider records confirm the required refund of {required:.2f} "
            f"{refund.currency} has settled. Refund reference: {refund.refund_id}.",
        )
    return RefundStateProjection(
        WorkflowStatus.ESCALATED,
        WorkflowOutcome.NEEDS_REVIEW,
        "The settled refund amount does not establish full resolution of this issue. "
        "An operator must check the remaining obligation and refund records.",
        "refund_settlement_incomplete",
    )


def refresh_refund_result(
    session_factory: sessionmaker[Session],
    result: WorkflowResult,
    clock: Callable[[], datetime],
) -> WorkflowResult:
    """Refresh a stored execution without executing another payment write."""
    if result.outcome not in REFUND_OUTCOMES and result.error_code not in REFUND_REVIEW_ERRORS:
        return result
    refund_id = result.verified_resource_id or (
        result.operation.resource_id if result.operation is not None else None
    )
    if refund_id is None:
        return result
    with session_factory() as session:
        refund = session.get(RefundRecord, refund_id)
        issue = session.get(CaseIssueRecord, result.issue_id)
        if refund is None or issue is None or not _refund_matches_issue(refund, issue):
            return result
        projection = refund_state_projection(session, refund)
        run = session.get(WorkflowRunRecord, result.workflow_id)
        if (
            run is not None
            and run.status == WorkflowLifecycleStatus.ESCALATED
            and run.error_code == "refund_settlement_incomplete"
        ):
            # A later, separately approved portion may settle the case, but must not
            # rewrite this earlier attempt's terminal review outcome on a GET.
            projection = RefundStateProjection(
                WorkflowStatus.ESCALATED,
                WorkflowOutcome.NEEDS_REVIEW,
                run.error_message or "This attempt required review of an incomplete settlement.",
                run.error_code,
            )
    outcome = projection.outcome
    if outcome == WorkflowOutcome.WAITING_EXTERNAL and result.operation is not None:
        outcome = WorkflowOutcome.REFUND_SUBMITTED
    response = CustomerResponseComposer().compose(
        status=projection.status,
        outcome=outcome,
        issue_id=result.issue_id,
        verified_resource_id=refund_id,
        existing_refund_id=refund_id,
        error_code=projection.error_code,
        policy_citations=result.policy_citations,
        generated_at=clock(),
    )
    return WorkflowResult.model_validate(
        {
            **result.model_dump(),
            "status": projection.status,
            "outcome": outcome,
            "verified_resource_id": refund_id,
            "resolution_summary": projection.summary,
            "error_code": projection.error_code,
            "error_message": projection.summary if projection.error_code else None,
            "final_response": response,
        }
    )


def synchronize_refund_state(
    session: Session,
    refund: RefundRecord,
    now: datetime,
    *,
    issue_id: str | None = None,
) -> RefundStateProjection:
    """Project one provider observation into its case in the caller's transaction."""
    issue = session.get(CaseIssueRecord, issue_id or refund.issue_id)
    if issue is None or not _refund_matches_issue(refund, issue):
        return refund_state_projection(session, refund)
    session.scalar(
        select(OrderRecord).where(OrderRecord.order_id == refund.order_id).with_for_update()
    )
    customer_case = session.scalar(
        select(CaseRecord).where(CaseRecord.case_id == issue.case_id).with_for_update()
    )
    if customer_case is None:
        return refund_state_projection(session, refund)
    # A read may have loaded this refund before waiting for the order lock.
    # Reload after serialization so an older identity-map value cannot reopen it.
    session.flush()
    session.refresh(refund)
    session.refresh(issue, with_for_update=True)
    projection = refund_state_projection(session, refund)
    resolution_refund = refund
    latest = session.scalar(
        select(RefundRecord)
        .where(RefundRecord.issue_id == issue.issue_id)
        .order_by(RefundRecord.created_at.desc(), RefundRecord.refund_id.desc())
        .limit(1)
    )
    # A late notification or an old execution view must not replace a newer recovery attempt.
    if latest is not None and latest.created_at > refund.created_at:
        projection = refund_state_projection(session, latest)
        resolution_refund = latest
    elif refund.status in {RefundStatus.FAILED, RefundStatus.CANCELLED}:
        # Providers or test clocks may timestamp an authorized retry at the same
        # precision as its failed predecessor. IDs are not a chronology signal.
        replacement = session.scalar(
            select(RefundRecord)
            .where(
                RefundRecord.issue_id == issue.issue_id,
                RefundRecord.created_at >= refund.created_at,
                RefundRecord.status.in_((*PENDING_REFUND_STATUSES, RefundStatus.COMPLETED)),
            )
            .order_by(RefundRecord.created_at.desc(), RefundRecord.refund_id.desc())
            .limit(1)
        )
        if replacement is not None and _refund_matches_issue(replacement, issue):
            projection = refund_state_projection(session, replacement)
            resolution_refund = replacement
    issue.finding = IssueFinding.CONFIRMED
    if projection.outcome == WorkflowOutcome.REFUND_SETTLED:
        issue.status = CaseIssueStatus.RESOLVED
        verification_status = VerificationStatus.PASSED
        resolution = session.get(CaseIssueResolutionRecord, issue.issue_id)
        if resolution is None:
            resolution = CaseIssueResolutionRecord(issue_id=issue.issue_id)
            session.add(resolution)
        resolution.summary = projection.summary
        resolution.resolved_at = resolution_refund.completed_at or now
    else:
        issue.status = (
            CaseIssueStatus.ESCALATED
            if projection.outcome == WorkflowOutcome.NEEDS_REVIEW
            else CaseIssueStatus.VERIFYING
        )
        verification_status = (
            VerificationStatus.FAILED
            if projection.outcome == WorkflowOutcome.NEEDS_REVIEW
            else VerificationStatus.PENDING
        )
        resolution = session.get(CaseIssueResolutionRecord, issue.issue_id)
        if resolution is not None:
            session.delete(resolution)
    verification = session.get(CaseIssueVerificationRecord, issue.issue_id)
    if verification is None:
        verification = CaseIssueVerificationRecord(issue_id=issue.issue_id)
        session.add(verification)
    verification.status = verification_status
    verification.summary = projection.summary
    verification.checked_at = now
    evidence_key = f"{issue.issue_id}:{refund.refund_id}".encode()
    evidence_id = f"REFUND-STATE-{sha256(evidence_key).hexdigest()[:32]}"
    evidence = session.get(CaseIssueEvidenceRecord, evidence_id)
    if evidence is None:
        evidence = CaseIssueEvidenceRecord(
            evidence_id=evidence_id,
            issue_id=issue.issue_id,
            source="payment-provider-status",
            reference_id=refund.refund_id,
        )
        session.add(evidence)
    evidence.summary = f"Refund {refund.refund_id}: {refund.status.value}. {projection.summary}"
    evidence.collected_at = now
    _refresh_case_status(session, customer_case, now)
    return projection


def _refund_matches_issue(refund: RefundRecord, issue: CaseIssueRecord) -> bool:
    if refund.order_id != issue.order_id:
        return False
    if refund.kind == RefundKind.RETURN:
        return (
            issue.issue_type
            in {
                CaseIssueType.MISSING_RETURN_REFUND,
                CaseIssueType.INCORRECT_REFUND_AMOUNT,
            }
            and issue.return_id == refund.return_id
        )
    if refund.kind == RefundKind.CANCELLED_ORDER:
        return issue.issue_type == CaseIssueType.CANCELLED_ORDER_CHARGE and any(
            link.payment_id == refund.payment_id for link in issue.payment_links
        )
    return (
        refund.kind == RefundKind.DUPLICATE_CHARGE
        and issue.issue_type == CaseIssueType.DUPLICATE_CHARGE
        and any(link.payment_id == refund.payment_id for link in issue.payment_links)
    )


def _refresh_case_status(session: Session, customer_case: CaseRecord, now: datetime) -> None:
    session.flush()
    statuses = list(
        session.scalars(
            select(CaseIssueRecord.status).where(CaseIssueRecord.case_id == customer_case.case_id)
        )
    )
    if statuses and all(status == CaseIssueStatus.RESOLVED for status in statuses):
        customer_case.status = CaseStatus.RESOLVED
    elif CaseIssueStatus.ESCALATED in statuses:
        customer_case.status = CaseStatus.ESCALATED
    elif CaseIssueStatus.ACTION_PENDING in statuses:
        customer_case.status = CaseStatus.PENDING_APPROVAL
    else:
        customer_case.status = CaseStatus.IN_PROGRESS
    customer_case.updated_at = now


def synchronize_case_state(
    session_factory: sessionmaker[Session],
    execution: WorkflowPause | WorkflowResult,
    clock: Callable[[], datetime],
) -> None:
    now = clock()
    with session_factory.begin() as session:
        customer_case = session.get(CaseRecord, execution.case_id)
        issue = session.get(CaseIssueRecord, execution.issue_id)
        if customer_case is None or issue is None or issue.case_id != customer_case.case_id:
            return
        if isinstance(execution, WorkflowPause):
            issue.status = CaseIssueStatus.ACTION_PENDING
            _refresh_case_status(session, customer_case, now)
            return
        issue.finding = execution.finding
        refund_id = execution.verified_resource_id or (
            execution.operation.resource_id if execution.operation is not None else None
        )
        refund = session.get(RefundRecord, refund_id) if refund_id else None
        if refund is not None and (
            execution.outcome in REFUND_OUTCOMES or execution.error_code in REFUND_REVIEW_ERRORS
        ):
            synchronize_refund_state(session, refund, now, issue_id=issue.issue_id)
            if execution.operation is not None:
                action_id = f"CASE-ACTION-{execution.operation.operation_id}"
                if session.get(CaseIssueActionRecord, action_id) is None:
                    session.add(
                        CaseIssueActionRecord(
                            action_id=action_id,
                            issue_id=issue.issue_id,
                            name="submit refund request",
                            status=IssueActionStatus.EXECUTED,
                            created_at=now,
                            completed_at=now,
                        )
                    )
            return
        if execution.outcome == WorkflowOutcome.NO_ACTION_REQUIRED:
            issue.status = CaseIssueStatus.RESOLVED
            issue.finding = IssueFinding.REJECTED
            verification = session.get(CaseIssueVerificationRecord, issue.issue_id)
            if verification is None:
                verification = CaseIssueVerificationRecord(issue_id=issue.issue_id)
                session.add(verification)
            verification.status = VerificationStatus.PASSED
            verification.summary = execution.resolution_summary
            verification.checked_at = now
            resolution = session.get(CaseIssueResolutionRecord, issue.issue_id)
            if resolution is None:
                resolution = CaseIssueResolutionRecord(issue_id=issue.issue_id)
                session.add(resolution)
            resolution.summary = execution.resolution_summary
            resolution.resolved_at = now
        elif execution.outcome == WorkflowOutcome.NEEDS_REVIEW:
            issue.status = CaseIssueStatus.ESCALATED
        else:
            issue.status = CaseIssueStatus.VERIFYING
        _refresh_case_status(session, customer_case, now)
