"""Add durable workflow lifecycle and approval records.

Revision ID: 0005_durable_workflows
Revises: 0004_knowledge_baseline
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_durable_workflows"
down_revision: str | None = "0004_knowledge_baseline"
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
        "workflow_runs",
        sa.Column("workflow_id", sa.String(length=100), primary_key=True),
        sa.Column("thread_id", sa.String(length=100), nullable=False, unique=True),
        sa.Column("case_id", sa.String(length=100), nullable=False),
        sa.Column("issue_id", sa.String(length=100), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            text_enum(
                "running",
                "waiting_approval",
                "completed",
                "escalated",
                "failed",
                name="workflow_lifecycle_status",
            ),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            text_enum(
                "action_verified",
                "waiting_external",
                "needs_review",
                name="workflow_run_outcome",
            ),
        ),
        sa.Column("requested_by", sa.String(length=100), nullable=False),
        sa.Column(
            "requested_role",
            text_enum(
                "agent",
                "operator",
                "approver",
                "system",
                name="workflow_requested_role",
            ),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("updated_at >= created_at", name="ck_workflow_runs_timestamp_order"),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name="ck_workflow_runs_completion_order",
        ),
        sa.CheckConstraint(
            "status NOT IN ('completed', 'escalated', 'failed') OR completed_at IS NOT NULL",
            name="ck_workflow_runs_terminal_time",
        ),
    )
    op.create_index("ix_workflow_runs_case_id", "workflow_runs", ["case_id"])
    op.create_index("ix_workflow_runs_issue_id", "workflow_runs", ["issue_id"])

    op.create_table(
        "workflow_approvals",
        sa.Column("approval_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.String(length=100),
            sa.ForeignKey("workflow_runs.workflow_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "operation_type",
            text_enum(
                "issue_refund",
                "send_notification",
                "create_ticket",
                name="workflow_approval_operation_type",
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            text_enum(
                "pending",
                "approved",
                "rejected",
                name="workflow_approval_status",
            ),
            nullable=False,
        ),
        sa.Column("case_id", sa.String(length=100), nullable=False),
        sa.Column("issue_id", sa.String(length=100), nullable=False),
        sa.Column("payment_id", sa.String(length=100), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("reason", sa.String(length=1000), nullable=False),
        sa.Column("requested_by", sa.String(length=100), nullable=False),
        sa.Column(
            "requested_role",
            text_enum(
                "agent",
                "operator",
                "approver",
                "system",
                name="workflow_approval_requested_role",
            ),
            nullable=False,
        ),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.String(length=100)),
        sa.Column(
            "decided_role",
            text_enum(
                "agent",
                "operator",
                "approver",
                "system",
                name="workflow_approval_decided_role",
            ),
        ),
        sa.Column("decision_note", sa.String(length=1000)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("amount > 0", name="ck_workflow_approvals_positive_amount"),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_workflow_approvals_currency",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND decided_by IS NULL AND decided_role IS NULL "
            "AND decided_at IS NULL) OR "
            "(status != 'pending' AND decided_by IS NOT NULL "
            "AND decided_role IS NOT NULL AND decided_at IS NOT NULL)",
            name="ck_workflow_approvals_decision_state",
        ),
        sa.UniqueConstraint(
            "workflow_id",
            "operation_type",
            name="uq_workflow_approvals_action",
        ),
    )
    op.create_index("ix_workflow_approvals_workflow_id", "workflow_approvals", ["workflow_id"])

    op.create_table(
        "workflow_events",
        sa.Column("event_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.String(length=100),
            sa.ForeignKey("workflow_runs.workflow_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "event_type",
            text_enum(
                "started",
                "approval_requested",
                "approval_approved",
                "approval_rejected",
                "completed",
                "escalated",
                "failed",
                name="workflow_event_type",
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(length=100)),
        sa.Column(
            "actor_role",
            text_enum(
                "agent",
                "operator",
                "approver",
                "system",
                name="workflow_event_actor_role",
            ),
        ),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "workflow_id",
            "sequence_number",
            name="uq_workflow_events_sequence",
        ),
    )
    op.create_index("ix_workflow_events_workflow_id", "workflow_events", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_workflow_events_workflow_id", table_name="workflow_events")
    op.drop_table("workflow_events")
    op.drop_index("ix_workflow_approvals_workflow_id", table_name="workflow_approvals")
    op.drop_table("workflow_approvals")
    op.drop_index("ix_workflow_runs_issue_id", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_case_id", table_name="workflow_runs")
    op.drop_table("workflow_runs")
