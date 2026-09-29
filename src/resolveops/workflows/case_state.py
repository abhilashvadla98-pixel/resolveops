from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from resolveops.database.records import (
    CaseIssueActionRecord,
    CaseIssueRecord,
    CaseIssueResolutionRecord,
    CaseIssueVerificationRecord,
    CaseRecord,
)
from resolveops.models.case import (
    CaseIssueStatus,
    CaseStatus,
    IssueActionStatus,
    VerificationStatus,
)
from resolveops.workflows.models import WorkflowOutcome, WorkflowPause, WorkflowResult


def synchronize_case_state(
    session_factory: sessionmaker[Session],
    execution: WorkflowPause | WorkflowResult,
    clock: Callable[[], datetime],
) -> None:
    now = clock()
    with session_factory.begin() as session:
        customer_case = session.get(CaseRecord, execution.case_id)
        issue = session.get(CaseIssueRecord, execution.issue_id)
        if customer_case is None or issue is None:
            return

        if isinstance(execution, WorkflowPause):
            issue.status = CaseIssueStatus.ACTION_PENDING
            customer_case.status = CaseStatus.PENDING_APPROVAL
            customer_case.updated_at = now
            return

        issue.finding = execution.finding
        if execution.outcome == WorkflowOutcome.ACTION_VERIFIED:
            issue.status = CaseIssueStatus.RESOLVED
            verification = session.get(CaseIssueVerificationRecord, issue.issue_id)
            if verification is None:
                verification = CaseIssueVerificationRecord(issue_id=issue.issue_id)
                session.add(verification)
            verification.status = VerificationStatus.PASSED
            verification.summary = (
                "Fresh provider and database state matched the authorized action."
            )
            verification.checked_at = now

            resolution = session.get(CaseIssueResolutionRecord, issue.issue_id)
            if resolution is None:
                resolution = CaseIssueResolutionRecord(issue_id=issue.issue_id)
                session.add(resolution)
            resolution.summary = execution.resolution_summary
            resolution.resolved_at = now

            if execution.operation is not None:
                action_id = f"CASE-ACTION-{execution.operation.operation_id}"
                if session.get(CaseIssueActionRecord, action_id) is None:
                    session.add(
                        CaseIssueActionRecord(
                            action_id=action_id,
                            issue_id=issue.issue_id,
                            name=execution.operation.operation_type.value.replace("_", " "),
                            status=IssueActionStatus.EXECUTED,
                            created_at=now,
                            completed_at=now,
                        )
                    )
            unresolved_count = session.scalar(
                select(CaseIssueRecord)
                .where(
                    CaseIssueRecord.case_id == customer_case.case_id,
                    CaseIssueRecord.issue_id != issue.issue_id,
                    CaseIssueRecord.status != CaseIssueStatus.RESOLVED,
                )
                .limit(1)
            )
            customer_case.status = (
                CaseStatus.IN_PROGRESS if unresolved_count is not None else CaseStatus.RESOLVED
            )
        elif execution.outcome == WorkflowOutcome.NEEDS_REVIEW:
            issue.status = CaseIssueStatus.ESCALATED
            customer_case.status = CaseStatus.ESCALATED
        else:
            issue.status = CaseIssueStatus.VERIFYING
            customer_case.status = CaseStatus.IN_PROGRESS
        customer_case.updated_at = now
