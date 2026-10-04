import hashlib
from datetime import UTC, datetime

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from resolveops.database.employee_it_records import (
    EmployeeRecord,
    EnterpriseIdentityRecord,
    GitAccountRecord,
    GitRepositoryRecord,
    ITAccessCaseRecord,
    ITAccessRequestRecord,
    ITTicketRecord,
)
from resolveops.employee_it.models import (
    AccessRequestStatus,
    EmployeeAccessSnapshot,
    ITCaseStatus,
    ITTicketStatus,
    RepositoryAccessLevel,
)
from resolveops.employee_it.store import EmployeeITStore
from resolveops.models.common import DomainModel, Identifier
from resolveops.operations.errors import BusinessRuleError


class EmployeeRequestSubmission(DomainModel):
    source_message_id: Identifier
    repository_id: Identifier
    requested_level: RepositoryAccessLevel
    justification: str = Field(min_length=10, max_length=2000)
    demo_employee_id: Identifier | None = None


def submit_access_request(
    session: Session,
    body: EmployeeRequestSubmission,
    employee: EmployeeRecord,
    identity: EnterpriseIdentityRecord,
) -> EmployeeAccessSnapshot:
    if body.requested_level not in {RepositoryAccessLevel.READ, RepositoryAccessLevel.WRITE}:
        raise BusinessRuleError(
            "access_level_not_supported", "This workflow supports read or write access only."
        )
    repository = session.get(GitRepositoryRecord, body.repository_id)
    git_account = session.scalar(
        select(GitAccountRecord).where(GitAccountRecord.identity_id == identity.identity_id)
    )
    if repository is None or git_account is None:
        raise BusinessRuleError(
            "intake_dependency_missing", "A known repository and linked Git account are required."
        )
    digest = hashlib.sha256(
        f"{identity.identity_id}:{body.source_message_id}".encode()
    ).hexdigest()[:24]
    case_id = f"ITCASE-{digest}"
    existing = session.get(ITAccessCaseRecord, case_id)
    if existing is not None:
        snapshot = EmployeeITStore(session).get_snapshot(case_id)
        request = snapshot.access_request
        if (
            request.employee_id != employee.employee_id
            or request.identity_id != identity.identity_id
            or request.repository_id != body.repository_id
            or request.requested_level != body.requested_level
            or request.justification != body.justification
        ):
            raise BusinessRuleError(
                "intake_message_conflict",
                "This source message ID was used for a different request.",
            )
        return snapshot
    now = datetime.now(UTC)
    request_id = f"ITREQUEST-{digest}"
    session.add(
        ITAccessCaseRecord(
            case_id=case_id,
            employee_id=employee.employee_id,
            access_request_id=request_id,
            status=ITCaseStatus.OPEN,
            opened_at=now,
            updated_at=now,
        )
    )
    session.flush()
    session.add_all(
        [
            ITAccessRequestRecord(
                access_request_id=request_id,
                case_id=case_id,
                employee_id=employee.employee_id,
                identity_id=identity.identity_id,
                target_team_id=repository.owning_team_id,
                repository_id=repository.repository_id,
                requested_level=body.requested_level,
                justification=body.justification,
                status=AccessRequestStatus.PENDING_APPROVAL,
                requested_at=now,
                approved_by=None,
                approved_at=None,
            ),
            ITTicketRecord(
                ticket_id=f"ITTICKET-{digest}",
                case_id=case_id,
                subject=f"Access to {repository.name}",
                description=body.justification,
                status=ITTicketStatus.OPEN,
                created_at=now,
                updated_at=now,
            ),
        ]
    )
    session.flush()
    return EmployeeITStore(session).get_snapshot(case_id)
