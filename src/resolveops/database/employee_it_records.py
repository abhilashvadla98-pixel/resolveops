from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from resolveops.database.base import Base
from resolveops.database.records import UTCDateTime, enum_type
from resolveops.employee_it.models import (
    AccessRequestStatus,
    EmploymentStatus,
    GitAccountStatus,
    IdentityStatus,
    ITCaseStatus,
    ITNotificationStatus,
    ITTicketStatus,
    MembershipStatus,
    RepositoryAccessLevel,
)


class EmployeeRecord(Base):
    __tablename__ = "employees"

    employee_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(1000))
    work_email: Mapped[str] = mapped_column(String(320), unique=True)
    manager_employee_id: Mapped[str | None] = mapped_column(ForeignKey("employees.employee_id"))
    status: Mapped[EmploymentStatus] = mapped_column(
        enum_type(EmploymentStatus, "employment_status")
    )


class TeamRecord(Base):
    __tablename__ = "employee_teams"

    team_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(1000), unique=True)
    manager_employee_id: Mapped[str] = mapped_column(ForeignKey("employees.employee_id"))


class EmployeeTeamMembershipRecord(Base):
    __tablename__ = "employee_team_memberships"

    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.employee_id"), primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("employee_teams.team_id"), primary_key=True)
    status: Mapped[MembershipStatus] = mapped_column(
        enum_type(MembershipStatus, "employee_team_membership_status")
    )
    joined_at: Mapped[datetime] = mapped_column(UTCDateTime())


class EnterpriseIdentityRecord(Base):
    __tablename__ = "enterprise_identities"

    identity_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.employee_id"), unique=True)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[IdentityStatus] = mapped_column(
        enum_type(IdentityStatus, "enterprise_identity_status")
    )
    mfa_enrolled: Mapped[bool] = mapped_column(Boolean)


class DirectoryGroupRecord(Base):
    __tablename__ = "directory_groups"

    group_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(1000), unique=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("employee_teams.team_id"))
    purpose: Mapped[str] = mapped_column(Text)


class DirectoryGroupMembershipRecord(Base):
    __tablename__ = "directory_group_memberships"
    __table_args__ = (
        UniqueConstraint("group_id", "identity_id", name="uq_group_identity_membership"),
    )

    membership_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    group_id: Mapped[str] = mapped_column(ForeignKey("directory_groups.group_id"))
    identity_id: Mapped[str] = mapped_column(ForeignKey("enterprise_identities.identity_id"))
    status: Mapped[MembershipStatus] = mapped_column(
        enum_type(MembershipStatus, "directory_group_membership_status")
    )
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime())


class GitAccountRecord(Base):
    __tablename__ = "git_accounts"

    git_account_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    identity_id: Mapped[str] = mapped_column(
        ForeignKey("enterprise_identities.identity_id"), unique=True
    )
    username: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[GitAccountStatus] = mapped_column(
        enum_type(GitAccountStatus, "git_account_status")
    )


class GitRepositoryRecord(Base):
    __tablename__ = "git_repositories"

    repository_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(1000), unique=True)
    owning_team_id: Mapped[str] = mapped_column(ForeignKey("employee_teams.team_id"))
    required_group_id: Mapped[str] = mapped_column(ForeignKey("directory_groups.group_id"))


class GitRepositoryAccessRecord(Base):
    __tablename__ = "git_repository_access"
    __table_args__ = (
        UniqueConstraint(
            "repository_id", "git_account_id", name="uq_repository_git_account_access"
        ),
    )

    access_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    repository_id: Mapped[str] = mapped_column(ForeignKey("git_repositories.repository_id"))
    git_account_id: Mapped[str] = mapped_column(ForeignKey("git_accounts.git_account_id"))
    level: Mapped[RepositoryAccessLevel] = mapped_column(
        enum_type(RepositoryAccessLevel, "repository_access_level")
    )
    status: Mapped[MembershipStatus] = mapped_column(
        enum_type(MembershipStatus, "repository_access_status")
    )
    granted_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ITAccessCaseRecord(Base):
    __tablename__ = "it_access_cases"
    __table_args__ = (
        CheckConstraint("updated_at >= opened_at", name="ck_it_cases_timestamp_order"),
    )

    case_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.employee_id"))
    access_request_id: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[ITCaseStatus] = mapped_column(enum_type(ITCaseStatus, "it_case_status"))
    opened_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ITAccessRequestRecord(Base):
    __tablename__ = "it_access_requests"
    __table_args__ = (
        CheckConstraint(
            "approved_at IS NULL OR approved_at >= requested_at",
            name="ck_it_access_request_approval_order",
        ),
    )

    access_request_id: Mapped[str] = mapped_column(
        ForeignKey("it_access_cases.access_request_id"), primary_key=True
    )
    case_id: Mapped[str] = mapped_column(ForeignKey("it_access_cases.case_id"), unique=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.employee_id"))
    identity_id: Mapped[str] = mapped_column(ForeignKey("enterprise_identities.identity_id"))
    target_team_id: Mapped[str] = mapped_column(ForeignKey("employee_teams.team_id"))
    repository_id: Mapped[str] = mapped_column(ForeignKey("git_repositories.repository_id"))
    requested_level: Mapped[RepositoryAccessLevel] = mapped_column(
        enum_type(RepositoryAccessLevel, "access_request_level")
    )
    justification: Mapped[str] = mapped_column(Text)
    status: Mapped[AccessRequestStatus] = mapped_column(
        enum_type(AccessRequestStatus, "access_request_status")
    )
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime())
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("employees.employee_id"))
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ITTicketRecord(Base):
    __tablename__ = "it_tickets"
    __table_args__ = (
        CheckConstraint("updated_at >= created_at", name="ck_it_tickets_timestamp_order"),
    )

    ticket_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("it_access_cases.case_id"), unique=True)
    subject: Mapped[str] = mapped_column(String(1000))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[ITTicketStatus] = mapped_column(enum_type(ITTicketStatus, "it_ticket_status"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ITNotificationRecord(Base):
    __tablename__ = "it_notifications"

    notification_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("it_access_cases.case_id"))
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.employee_id"))
    recipient: Mapped[str] = mapped_column(String(320))
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[ITNotificationStatus] = mapped_column(
        enum_type(ITNotificationStatus, "it_notification_status")
    )
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime())
