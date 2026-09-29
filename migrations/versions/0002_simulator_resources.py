"""Add ticket, policy, and notification simulator records.

Revision ID: 0002_simulator_resources
Revises: 0001_customer_operations
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_simulator_resources"
down_revision: str | None = "0001_customer_operations"
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


def upgrade() -> None:
    op.create_table(
        "tickets",
        sa.Column("ticket_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(length=100),
            sa.ForeignKey("cases.case_id"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(length=1000), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            text_enum("open", "in_progress", "resolved", "closed", name="ticket_status"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("updated_at >= created_at", name="ck_tickets_timestamp_order"),
    )
    op.create_index("ix_tickets_case_id", "tickets", ["case_id"])

    op.create_table(
        "policies",
        sa.Column("policy_id", sa.String(length=100), primary_key=True),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            text_enum("draft", "active", "superseded", name="policy_status"),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=1000), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version > 0", name="ck_policies_positive_version"),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > effective_at",
            name="ck_policies_effective_order",
        ),
    )
    op.create_index("ix_policies_effective_at", "policies", ["effective_at"])

    op.create_table(
        "policy_issue_types",
        sa.Column(
            "policy_id",
            sa.String(length=100),
            sa.ForeignKey("policies.policy_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "issue_type",
            text_enum(
                "duplicate_charge",
                "missing_return_refund",
                name="policy_case_issue_type",
            ),
            primary_key=True,
        ),
    )

    op.create_table(
        "notifications",
        sa.Column("notification_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(length=100),
            sa.ForeignKey("cases.case_id"),
            nullable=False,
        ),
        sa.Column(
            "customer_id",
            sa.String(length=100),
            sa.ForeignKey("customers.customer_id"),
            nullable=False,
        ),
        sa.Column(
            "channel",
            text_enum("email", "sms", name="notification_channel"),
            nullable=False,
        ),
        sa.Column("recipient", sa.String(length=1000), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column(
            "status",
            text_enum("queued", "sent", "failed", name="notification_status"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status != 'sent' OR sent_at IS NOT NULL",
            name="ck_notifications_sent_at",
        ),
        sa.CheckConstraint(
            "sent_at IS NULL OR sent_at >= created_at",
            name="ck_notifications_delivery_order",
        ),
    )
    op.create_index("ix_notifications_case_id", "notifications", ["case_id"])
    op.create_index("ix_notifications_customer_id", "notifications", ["customer_id"])


def downgrade() -> None:
    op.drop_index("ix_notifications_customer_id", table_name="notifications")
    op.drop_index("ix_notifications_case_id", table_name="notifications")
    op.drop_table("notifications")
    op.drop_table("policy_issue_types")
    op.drop_index("ix_policies_effective_at", table_name="policies")
    op.drop_table("policies")
    op.drop_index("ix_tickets_case_id", table_name="tickets")
    op.drop_table("tickets")
