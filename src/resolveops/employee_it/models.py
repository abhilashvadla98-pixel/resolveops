from enum import Enum

from pydantic import EmailStr, Field, model_validator

from resolveops.models.common import AwareDatetime, DomainModel, Identifier, NonEmptyText


class EmploymentStatus(str, Enum):
    ACTIVE = "active"
    LEAVE = "leave"
    TERMINATED = "terminated"


class IdentityStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEPROVISIONED = "deprovisioned"


class MembershipStatus(str, Enum):
    ACTIVE = "active"
    PENDING = "pending"
    REVOKED = "revoked"


class GitAccountStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class RepositoryAccessLevel(str, Enum):
    READ = "read"
    WRITE = "write"
    MAINTAIN = "maintain"


class ITCaseStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    ACTION_PENDING = "action_pending"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class AccessRequestStatus(str, Enum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    FULFILLED = "fulfilled"
    REJECTED = "rejected"


class ITTicketStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"


class ITNotificationStatus(str, Enum):
    SENT = "sent"
    FAILED = "failed"


class Employee(DomainModel):
    employee_id: Identifier
    name: NonEmptyText
    work_email: EmailStr
    manager_employee_id: Identifier | None = None
    status: EmploymentStatus


class Team(DomainModel):
    team_id: Identifier
    name: NonEmptyText
    manager_employee_id: Identifier


class EmployeeTeamMembership(DomainModel):
    employee_id: Identifier
    team_id: Identifier
    status: MembershipStatus
    joined_at: AwareDatetime


class EnterpriseIdentity(DomainModel):
    identity_id: Identifier
    employee_id: Identifier
    username: Identifier
    status: IdentityStatus
    mfa_enrolled: bool


class DirectoryGroup(DomainModel):
    group_id: Identifier
    name: NonEmptyText
    team_id: Identifier
    purpose: NonEmptyText


class DirectoryGroupMembership(DomainModel):
    membership_id: Identifier
    group_id: Identifier
    identity_id: Identifier
    status: MembershipStatus
    granted_at: AwareDatetime


class GitAccount(DomainModel):
    git_account_id: Identifier
    identity_id: Identifier
    username: Identifier
    status: GitAccountStatus


class GitRepository(DomainModel):
    repository_id: Identifier
    name: NonEmptyText
    owning_team_id: Identifier
    required_group_id: Identifier


class GitRepositoryAccess(DomainModel):
    access_id: Identifier
    repository_id: Identifier
    git_account_id: Identifier
    level: RepositoryAccessLevel
    status: MembershipStatus
    granted_at: AwareDatetime


class ITAccessRequest(DomainModel):
    access_request_id: Identifier
    case_id: Identifier
    employee_id: Identifier
    identity_id: Identifier
    target_team_id: Identifier
    repository_id: Identifier
    requested_level: RepositoryAccessLevel
    justification: NonEmptyText
    status: AccessRequestStatus
    requested_at: AwareDatetime
    approved_by: Identifier | None = None
    approved_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_approval(self) -> "ITAccessRequest":
        if self.status in {AccessRequestStatus.APPROVED, AccessRequestStatus.FULFILLED}:
            if self.approved_by is None or self.approved_at is None:
                raise ValueError("approved and fulfilled requests require approval evidence")
        elif self.approved_by is not None or self.approved_at is not None:
            raise ValueError("unapproved requests cannot contain approval evidence")
        if self.approved_at is not None and self.approved_at < self.requested_at:
            raise ValueError("approval cannot predate the request")
        return self


class ITAccessCase(DomainModel):
    case_id: Identifier
    employee_id: Identifier
    access_request_id: Identifier
    status: ITCaseStatus
    opened_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_timestamps(self) -> "ITAccessCase":
        if self.updated_at < self.opened_at:
            raise ValueError("IT case update cannot predate opening")
        return self


class ITTicket(DomainModel):
    ticket_id: Identifier
    case_id: Identifier
    subject: NonEmptyText
    description: NonEmptyText
    status: ITTicketStatus
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ITNotification(DomainModel):
    notification_id: Identifier
    case_id: Identifier
    employee_id: Identifier
    recipient: EmailStr
    message: NonEmptyText
    status: ITNotificationStatus
    sent_at: AwareDatetime


class GrantRepositoryAccessRequest(DomainModel):
    idempotency_key: Identifier
    case_id: Identifier
    access_request_id: Identifier
    employee_id: Identifier
    identity_id: Identifier
    repository_id: Identifier
    access_level: RepositoryAccessLevel
    reason: NonEmptyText


class EmployeeAccessSnapshot(DomainModel):
    employee: Employee
    team: Team
    team_membership: EmployeeTeamMembership | None
    identity: EnterpriseIdentity
    git_account: GitAccount
    repository: GitRepository
    access_case: ITAccessCase
    access_request: ITAccessRequest
    group_membership: DirectoryGroupMembership | None
    repository_access: GitRepositoryAccess | None
    ticket: ITTicket
    notifications: list[ITNotification] = Field(default_factory=list)
