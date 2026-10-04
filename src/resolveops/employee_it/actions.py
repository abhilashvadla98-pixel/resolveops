from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from resolveops.database.employee_it_records import (
    DirectoryGroupMembershipRecord,
    DirectoryGroupRecord,
    EmployeeRecord,
    EmployeeTeamMembershipRecord,
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
from resolveops.employee_it.models import (
    AccessRequestStatus,
    EmploymentStatus,
    GitAccountStatus,
    GrantRepositoryAccessRequest,
    IdentityStatus,
    ITCaseStatus,
    ITNotificationStatus,
    ITTicketStatus,
    MembershipStatus,
    RepositoryAccessLevel,
)
from resolveops.operations.errors import BusinessRuleError, ResourceNotFoundError


def execute_repository_access(
    session: Session,
    access_id: str,
    request: GrantRepositoryAccessRequest,
    created_at: datetime,
) -> None:
    access_case = session.get(ITAccessCaseRecord, request.case_id)
    access_request = session.scalar(
        select(ITAccessRequestRecord)
        .where(ITAccessRequestRecord.access_request_id == request.access_request_id)
        .with_for_update()
    )
    if access_case is None or access_request is None:
        raise ResourceNotFoundError(
            "access_case_not_found", "IT access case or request does not exist"
        )
    if (
        access_case.access_request_id != access_request.access_request_id
        or access_request.case_id != access_case.case_id
        or access_request.employee_id != request.employee_id
        or access_request.identity_id != request.identity_id
        or access_request.repository_id != request.repository_id
        or access_request.requested_level != request.access_level
    ):
        raise BusinessRuleError(
            "access_scope_mismatch", "grant request does not match the approved IT case"
        )

    employee = session.get(EmployeeRecord, request.employee_id)
    identity = session.get(EnterpriseIdentityRecord, request.identity_id)
    team = session.get(TeamRecord, access_request.target_team_id)
    repository = session.get(GitRepositoryRecord, request.repository_id)
    git_account = session.scalar(
        select(GitAccountRecord).where(GitAccountRecord.identity_id == request.identity_id)
    )
    ticket = session.scalar(
        select(ITTicketRecord).where(ITTicketRecord.case_id == request.case_id).with_for_update()
    )
    if any(item is None for item in (employee, identity, team, repository, git_account, ticket)):
        raise ResourceNotFoundError(
            "access_dependency_missing", "IT access dependencies are incomplete"
        )
    assert employee is not None
    assert identity is not None
    assert team is not None
    assert repository is not None
    assert git_account is not None
    assert ticket is not None

    membership = session.get(
        EmployeeTeamMembershipRecord,
        {"employee_id": request.employee_id, "team_id": team.team_id},
    )
    group = session.get(DirectoryGroupRecord, repository.required_group_id)
    if request.access_level not in {RepositoryAccessLevel.READ, RepositoryAccessLevel.WRITE}:
        raise BusinessRuleError(
            "access_level_not_supported", "Only read or write access is supported"
        )
    if employee.status != EmploymentStatus.ACTIVE:
        raise BusinessRuleError("employee_inactive", "employee must be active")
    if identity.employee_id != employee.employee_id or identity.status != IdentityStatus.ACTIVE:
        raise BusinessRuleError(
            "identity_ineligible", "identity must be active and owned by employee"
        )
    if not identity.mfa_enrolled:
        raise BusinessRuleError("mfa_required", "MFA enrollment is required")
    if git_account.status != GitAccountStatus.ACTIVE:
        raise BusinessRuleError("git_account_inactive", "Git account must be active")
    if membership is None or membership.status != MembershipStatus.ACTIVE:
        raise BusinessRuleError(
            "team_membership_required", "active target-team membership is required"
        )
    if repository.owning_team_id != team.team_id or group is None or group.team_id != team.team_id:
        raise BusinessRuleError(
            "repository_policy_mismatch", "repository access mapping is invalid"
        )
    if (
        access_request.status != AccessRequestStatus.APPROVED
        or access_request.approved_by != team.manager_employee_id
        or access_request.approved_at is None
        or access_request.approved_by == employee.employee_id
    ):
        raise BusinessRuleError(
            "manager_approval_required", "target-team manager approval is required"
        )
    manager = session.get(EmployeeRecord, access_request.approved_by)
    if manager is None or manager.status != EmploymentStatus.ACTIVE:
        raise BusinessRuleError("manager_inactive", "The approving manager must still be active")

    existing_access = session.scalar(
        select(GitRepositoryAccessRecord).where(
            GitRepositoryAccessRecord.repository_id == repository.repository_id,
            GitRepositoryAccessRecord.git_account_id == git_account.git_account_id,
        )
    )
    if existing_access is not None:
        raise BusinessRuleError("repository_access_exists", "repository access already exists")
    group_membership = session.scalar(
        select(DirectoryGroupMembershipRecord).where(
            DirectoryGroupMembershipRecord.group_id == repository.required_group_id,
            DirectoryGroupMembershipRecord.identity_id == identity.identity_id,
        )
    )
    if group_membership is not None:
        raise BusinessRuleError(
            "group_membership_conflict",
            "Existing partial directory access must be reconciled by an operator.",
        )
    session.add(
        DirectoryGroupMembershipRecord(
            membership_id=f"GM-{access_id}",
            group_id=repository.required_group_id,
            identity_id=identity.identity_id,
            status=MembershipStatus.ACTIVE,
            granted_at=created_at,
        )
    )
    session.add(
        GitRepositoryAccessRecord(
            access_id=access_id,
            repository_id=repository.repository_id,
            git_account_id=git_account.git_account_id,
            level=request.access_level,
            status=MembershipStatus.ACTIVE,
            granted_at=created_at,
        )
    )
    access_request.status = AccessRequestStatus.FULFILLED
    access_case.status = ITCaseStatus.RESOLVED
    access_case.updated_at = created_at
    ticket.status = ITTicketStatus.RESOLVED
    ticket.updated_at = created_at
    session.add(
        ITNotificationRecord(
            notification_id=f"ITNOTE-{access_id}",
            case_id=access_case.case_id,
            employee_id=employee.employee_id,
            recipient=employee.work_email,
            message=(
                f"Access to {repository.name} was granted at {request.access_level.value} level."
            ),
            status=ITNotificationStatus.SENT,
            sent_at=created_at,
        )
    )


def verify_repository_access(
    session: Session,
    access_id: str,
    request: GrantRepositoryAccessRequest,
) -> bool:
    access = session.get(GitRepositoryAccessRecord, access_id)
    access_request = session.get(ITAccessRequestRecord, request.access_request_id)
    access_case = session.get(ITAccessCaseRecord, request.case_id)
    repository = session.get(GitRepositoryRecord, request.repository_id)
    identity = session.get(EnterpriseIdentityRecord, request.identity_id)
    ticket = session.scalar(select(ITTicketRecord).where(ITTicketRecord.case_id == request.case_id))
    if any(
        item is None for item in (access, access_request, access_case, repository, identity, ticket)
    ):
        return False
    assert access is not None
    assert access_request is not None
    assert access_case is not None
    assert repository is not None
    assert identity is not None
    assert ticket is not None
    group_membership = session.scalar(
        select(DirectoryGroupMembershipRecord).where(
            DirectoryGroupMembershipRecord.group_id == repository.required_group_id,
            DirectoryGroupMembershipRecord.identity_id == identity.identity_id,
            DirectoryGroupMembershipRecord.status == MembershipStatus.ACTIVE,
        )
    )
    notification = session.scalar(
        select(ITNotificationRecord).where(
            ITNotificationRecord.case_id == request.case_id,
            ITNotificationRecord.status == ITNotificationStatus.SENT,
        )
    )
    return bool(
        access.repository_id == request.repository_id
        and access.level == request.access_level
        and access.status == MembershipStatus.ACTIVE
        and access_request.status == AccessRequestStatus.FULFILLED
        and access_case.status == ITCaseStatus.RESOLVED
        and ticket.status == ITTicketStatus.RESOLVED
        and group_membership is not None
        and notification is not None
    )
