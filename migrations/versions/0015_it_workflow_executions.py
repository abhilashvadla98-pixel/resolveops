"""Persist terminal IT workflow outcomes.

Revision ID: 0015_it_workflow_executions
Revises: 0014_it_access_approvals
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_it_workflow_executions"
down_revision: str | None = "0014_it_access_approvals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "it_workflow_executions",
        sa.Column("workflow_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(length=100),
            sa.ForeignKey("it_access_cases.case_id"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "received",
                "investigating",
                "policy_review",
                "waiting_approval",
                "action_pending",
                "executing",
                "verifying",
                "completed",
                "waiting_external",
                "escalated",
                name="it_workflow_status",
                length=32,
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            sa.Enum(
                "access_verified",
                "already_satisfied",
                "needs_review",
                name="it_workflow_outcome",
                length=32,
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "decision",
            sa.Enum(
                "grant_access",
                "no_action",
                "escalate",
                name="it_workflow_decision",
                length=32,
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("verified_access_id", sa.String(length=100), nullable=True),
        sa.Column("resolution_summary", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("node_history", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("completed_at >= created_at", name="ck_it_workflow_timestamp_order"),
    )
    op.create_index(
        "ix_it_workflow_executions_case_id",
        "it_workflow_executions",
        ["case_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_it_workflow_executions_case_id", table_name="it_workflow_executions")
    op.drop_table("it_workflow_executions")
