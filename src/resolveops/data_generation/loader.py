import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session

from resolveops.data_generation.validation import validate_dataset
from resolveops.database.action_records import (
    AuditEventRecord,
    OperationRecord,
    ReliabilityEventRecord,
)
from resolveops.database.employee_it_records import (
    DirectoryGroupMembershipRecord,
    DirectoryGroupRecord,
    EmployeeRecord,
    EnterpriseIdentityRecord,
    GitAccountRecord,
    GitRepositoryAccessRecord,
    GitRepositoryRecord,
    ITAccessCaseRecord,
    ITAccessRequestRecord,
    ITNotificationRecord,
    ITTicketRecord,
    TeamRecord,
)
from resolveops.database.records import (
    CaseIssueActionRecord,
    CaseIssueEvidenceRecord,
    CaseIssuePaymentRecord,
    CaseIssueRecord,
    CaseIssueResolutionRecord,
    CaseIssueVerificationRecord,
    CaseRecord,
    CustomerRecord,
    OrderItemRecord,
    OrderRecord,
    PaymentRecord,
    RefundRecord,
    ReturnItemRecord,
    ReturnRecord,
)
from resolveops.database.simulator_records import (
    NotificationRecord,
    PolicyIssueTypeRecord,
    PolicyRecord,
)
from resolveops.database.workflow_records import (
    WorkflowApprovalRecord,
    WorkflowEventRecord,
    WorkflowRunRecord,
)

LOAD_ORDER: tuple[tuple[str, type[Any]], ...] = (
    ("customers", CustomerRecord),
    ("employees", EmployeeRecord),
    ("employee_teams", TeamRecord),
    ("enterprise_identities", EnterpriseIdentityRecord),
    ("directory_groups", DirectoryGroupRecord),
    ("git_accounts", GitAccountRecord),
    ("git_repositories", GitRepositoryRecord),
    ("policies", PolicyRecord),
    ("policy_issue_types", PolicyIssueTypeRecord),
    ("orders", OrderRecord),
    ("order_items", OrderItemRecord),
    ("payments", PaymentRecord),
    ("returns", ReturnRecord),
    ("return_items", ReturnItemRecord),
    ("cases", CaseRecord),
    ("case_issues", CaseIssueRecord),
    ("case_issue_payments", CaseIssuePaymentRecord),
    ("case_issue_evidence", CaseIssueEvidenceRecord),
    ("workflow_runs", WorkflowRunRecord),
    ("workflow_approvals", WorkflowApprovalRecord),
    ("workflow_events", WorkflowEventRecord),
    ("case_issue_actions", CaseIssueActionRecord),
    ("operations", OperationRecord),
    ("case_issue_verifications", CaseIssueVerificationRecord),
    ("refunds", RefundRecord),
    ("case_issue_resolutions", CaseIssueResolutionRecord),
    ("audit_events", AuditEventRecord),
    ("operation_reliability_events", ReliabilityEventRecord),
    ("notifications", NotificationRecord),
    ("it_access_cases", ITAccessCaseRecord),
    ("it_access_requests", ITAccessRequestRecord),
    ("it_tickets", ITTicketRecord),
    ("directory_group_memberships", DirectoryGroupMembershipRecord),
    ("git_repository_access", GitRepositoryAccessRecord),
    ("it_notifications", ITNotificationRecord),
)


def _convert_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key.endswith("_at") and isinstance(value, str):
        return datetime.fromisoformat(value)
    if key in {"amount", "total_amount", "unit_price", "classification_confidence"}:
        return Decimal(str(value))
    return value


def _read_entity(path: Path, allowed_fields: set[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if not line.strip():
                continue
            raw = json.loads(line)
            result.append(
                {
                    key: _convert_value(key, value)
                    for key, value in raw.items()
                    if key in allowed_fields
                }
            )
    return result


def load_dataset(session: Session, dataset_dir: Path, *, batch_size: int = 1_000) -> dict[str, int]:
    report = validate_dataset(dataset_dir)
    if not report.passed:
        raise ValueError(f"dataset failed {len(report.failures)} quality checks; load refused")
    loaded: dict[str, int] = {}
    for entity, record_type in LOAD_ORDER:
        path = dataset_dir / f"{entity}.jsonl"
        if not path.exists():
            continue
        allowed_fields = {column.key for column in record_type.__table__.columns}
        records = _read_entity(path, allowed_fields)
        for offset in range(0, len(records), batch_size):
            session.execute(insert(record_type), records[offset : offset + batch_size])
        loaded[entity] = len(records)
    session.commit()
    return loaded
