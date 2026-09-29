"""Add the Employee and IT access domain.

Revision ID: 0008_employee_it_domain
Revises: 0007_event_ingestion
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_employee_it_domain"
down_revision: str | None = "0007_event_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def text_enum(*values: str, name: str, length: int = 32) -> sa.Enum:
    return sa.Enum(
        *values,
        name=name,
        length=length,
        native_enum=False,
        create_constraint=True,
    )


def replace_check(table: str, name: str, column: str, values: tuple[str, ...]) -> None:
    quoted = ", ".join(f"'{value}'" for value in values)
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(name, type_="check")
        batch.create_check_constraint(name, f"{column} IN ({quoted})")


def upgrade() -> None:
    issue_types = ("duplicate_charge", "missing_return_refund", "repository_access")
    replace_check("case_issues", "case_issue_type", "issue_type", issue_types)
    replace_check("policy_issue_types", "policy_case_issue_type", "issue_type", issue_types)
    replace_check(
        "knowledge_document_issue_types",
        "knowledge_case_issue_type",
        "issue_type",
        issue_types,
    )
    replace_check(
        "operations",
        "operation_type",
        "operation_type",
        (
            "issue_refund",
            "send_notification",
            "create_ticket",
            "grant_repository_access",
        ),
    )

    op.create_table(
        "employees",
        sa.Column("employee_id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(1000), nullable=False),
        sa.Column("work_email", sa.String(320), nullable=False, unique=True),
        sa.Column("manager_employee_id", sa.String(100), sa.ForeignKey("employees.employee_id")),
        sa.Column(
            "status",
            text_enum("active", "leave", "terminated", name="employment_status"),
            nullable=False,
        ),
    )
    op.create_table(
        "employee_teams",
        sa.Column("team_id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(1000), nullable=False, unique=True),
        sa.Column(
            "manager_employee_id",
            sa.String(100),
            sa.ForeignKey("employees.employee_id"),
            nullable=False,
        ),
    )
    op.create_table(
        "employee_team_memberships",
        sa.Column(
            "employee_id",
            sa.String(100),
            sa.ForeignKey("employees.employee_id"),
            primary_key=True,
        ),
        sa.Column(
            "team_id",
            sa.String(100),
            sa.ForeignKey("employee_teams.team_id"),
            primary_key=True,
        ),
        sa.Column(
            "status",
            text_enum("active", "pending", "revoked", name="employee_team_membership_status"),
            nullable=False,
        ),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "enterprise_identities",
        sa.Column("identity_id", sa.String(100), primary_key=True),
        sa.Column(
            "employee_id",
            sa.String(100),
            sa.ForeignKey("employees.employee_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("username", sa.String(100), nullable=False, unique=True),
        sa.Column(
            "status",
            text_enum("active", "suspended", "deprovisioned", name="enterprise_identity_status"),
            nullable=False,
        ),
        sa.Column("mfa_enrolled", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "directory_groups",
        sa.Column("group_id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(1000), nullable=False, unique=True),
        sa.Column(
            "team_id", sa.String(100), sa.ForeignKey("employee_teams.team_id"), nullable=False
        ),
        sa.Column("purpose", sa.Text(), nullable=False),
    )
    op.create_table(
        "directory_group_memberships",
        sa.Column("membership_id", sa.String(100), primary_key=True),
        sa.Column(
            "group_id", sa.String(100), sa.ForeignKey("directory_groups.group_id"), nullable=False
        ),
        sa.Column(
            "identity_id",
            sa.String(100),
            sa.ForeignKey("enterprise_identities.identity_id"),
            nullable=False,
        ),
        sa.Column(
            "status",
            text_enum("active", "pending", "revoked", name="directory_group_membership_status"),
            nullable=False,
        ),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("group_id", "identity_id", name="uq_group_identity_membership"),
    )
    op.create_table(
        "git_accounts",
        sa.Column("git_account_id", sa.String(100), primary_key=True),
        sa.Column(
            "identity_id",
            sa.String(100),
            sa.ForeignKey("enterprise_identities.identity_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("username", sa.String(100), nullable=False, unique=True),
        sa.Column(
            "status",
            text_enum("active", "suspended", name="git_account_status"),
            nullable=False,
        ),
    )
    op.create_table(
        "git_repositories",
        sa.Column("repository_id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(1000), nullable=False, unique=True),
        sa.Column(
            "owning_team_id",
            sa.String(100),
            sa.ForeignKey("employee_teams.team_id"),
            nullable=False,
        ),
        sa.Column(
            "required_group_id",
            sa.String(100),
            sa.ForeignKey("directory_groups.group_id"),
            nullable=False,
        ),
    )
    op.create_table(
        "git_repository_access",
        sa.Column("access_id", sa.String(100), primary_key=True),
        sa.Column(
            "repository_id",
            sa.String(100),
            sa.ForeignKey("git_repositories.repository_id"),
            nullable=False,
        ),
        sa.Column(
            "git_account_id",
            sa.String(100),
            sa.ForeignKey("git_accounts.git_account_id"),
            nullable=False,
        ),
        sa.Column(
            "level",
            text_enum("read", "write", "maintain", name="repository_access_level"),
            nullable=False,
        ),
        sa.Column(
            "status",
            text_enum("active", "pending", "revoked", name="repository_access_status"),
            nullable=False,
        ),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "repository_id", "git_account_id", name="uq_repository_git_account_access"
        ),
    )
    op.create_table(
        "it_access_cases",
        sa.Column("case_id", sa.String(100), primary_key=True),
        sa.Column(
            "employee_id", sa.String(100), sa.ForeignKey("employees.employee_id"), nullable=False
        ),
        sa.Column("access_request_id", sa.String(100), nullable=False, unique=True),
        sa.Column(
            "status",
            text_enum(
                "open",
                "investigating",
                "action_pending",
                "resolved",
                "escalated",
                name="it_case_status",
            ),
            nullable=False,
        ),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("updated_at >= opened_at", name="ck_it_cases_timestamp_order"),
    )
    op.create_table(
        "it_access_requests",
        sa.Column(
            "access_request_id",
            sa.String(100),
            sa.ForeignKey("it_access_cases.access_request_id"),
            primary_key=True,
        ),
        sa.Column(
            "case_id",
            sa.String(100),
            sa.ForeignKey("it_access_cases.case_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "employee_id", sa.String(100), sa.ForeignKey("employees.employee_id"), nullable=False
        ),
        sa.Column(
            "identity_id",
            sa.String(100),
            sa.ForeignKey("enterprise_identities.identity_id"),
            nullable=False,
        ),
        sa.Column(
            "target_team_id",
            sa.String(100),
            sa.ForeignKey("employee_teams.team_id"),
            nullable=False,
        ),
        sa.Column(
            "repository_id",
            sa.String(100),
            sa.ForeignKey("git_repositories.repository_id"),
            nullable=False,
        ),
        sa.Column(
            "requested_level",
            text_enum("read", "write", "maintain", name="access_request_level"),
            nullable=False,
        ),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column(
            "status",
            text_enum(
                "pending_approval",
                "approved",
                "fulfilled",
                "rejected",
                name="access_request_status",
            ),
            nullable=False,
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by", sa.String(100), sa.ForeignKey("employees.employee_id")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "approved_at IS NULL OR approved_at >= requested_at",
            name="ck_it_access_request_approval_order",
        ),
    )
    op.create_table(
        "it_tickets",
        sa.Column("ticket_id", sa.String(100), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(100),
            sa.ForeignKey("it_access_cases.case_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("subject", sa.String(1000), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            text_enum("open", "in_progress", "resolved", name="it_ticket_status"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("updated_at >= created_at", name="ck_it_tickets_timestamp_order"),
    )
    op.create_table(
        "it_notifications",
        sa.Column("notification_id", sa.String(100), primary_key=True),
        sa.Column(
            "case_id", sa.String(100), sa.ForeignKey("it_access_cases.case_id"), nullable=False
        ),
        sa.Column(
            "employee_id", sa.String(100), sa.ForeignKey("employees.employee_id"), nullable=False
        ),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "status",
            text_enum("sent", "failed", name="it_notification_status"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM operation_reliability_events WHERE operation_id IN "
        "(SELECT operation_id FROM operations WHERE operation_type = 'grant_repository_access')"
    )
    op.execute(
        "DELETE FROM audit_events WHERE operation_id IN "
        "(SELECT operation_id FROM operations WHERE operation_type = 'grant_repository_access')"
    )
    op.execute("DELETE FROM operations WHERE operation_type = 'grant_repository_access'")
    op.drop_table("it_notifications")
    op.drop_table("it_tickets")
    op.drop_table("it_access_requests")
    op.drop_table("it_access_cases")
    op.drop_table("git_repository_access")
    op.drop_table("git_repositories")
    op.drop_table("git_accounts")
    op.drop_table("directory_group_memberships")
    op.drop_table("directory_groups")
    op.drop_table("enterprise_identities")
    op.drop_table("employee_team_memberships")
    op.drop_table("employee_teams")
    op.drop_table("employees")

    repository_policy_versions = (
        "SELECT document_version_id FROM knowledge_document_issue_types "
        "WHERE issue_type = 'repository_access'"
    )
    repository_policy_chunks = (
        "SELECT chunk_id FROM knowledge_chunks WHERE document_version_id IN ("
        f"{repository_policy_versions})"
    )
    op.execute(f"DELETE FROM knowledge_embeddings WHERE chunk_id IN ({repository_policy_chunks})")
    op.execute(
        f"DELETE FROM knowledge_chunks WHERE document_version_id IN ({repository_policy_versions})"
    )
    op.execute(
        "DELETE FROM knowledge_documents WHERE document_version_id IN ("
        f"{repository_policy_versions})"
    )
    op.execute("DELETE FROM knowledge_document_issue_types WHERE issue_type = 'repository_access'")
    old_issue_types = ("duplicate_charge", "missing_return_refund")
    replace_check("case_issues", "case_issue_type", "issue_type", old_issue_types)
    replace_check("policy_issue_types", "policy_case_issue_type", "issue_type", old_issue_types)
    replace_check(
        "knowledge_document_issue_types",
        "knowledge_case_issue_type",
        "issue_type",
        old_issue_types,
    )
    replace_check(
        "operations",
        "operation_type",
        "operation_type",
        ("issue_refund", "send_notification", "create_ticket"),
    )
