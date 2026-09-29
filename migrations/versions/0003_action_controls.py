"""Add idempotent operation and audit records.

Revision ID: 0003_action_controls
Revises: 0002_simulator_resources
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_action_controls"
down_revision: str | None = "0002_simulator_resources"
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
        "operations",
        sa.Column("operation_id", sa.String(length=100), primary_key=True),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column(
            "operation_type",
            text_enum(
                "issue_refund",
                "send_notification",
                "create_ticket",
                name="operation_type",
            ),
            nullable=False,
        ),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            text_enum(
                "started",
                "executed",
                "completed",
                "failed",
                "verification_failed",
                name="operation_status",
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column(
            "actor_role",
            text_enum("agent", "operator", "approver", "system", name="actor_role"),
            nullable=False,
        ),
        sa.Column("case_id", sa.String(length=100)),
        sa.Column("issue_id", sa.String(length=100)),
        sa.Column("result_resource_id", sa.String(length=100)),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("updated_at >= created_at", name="ck_operations_timestamp_order"),
        sa.CheckConstraint(
            "status NOT IN ('executed', 'completed') OR result_resource_id IS NOT NULL",
            name="ck_operations_result_state",
        ),
        sa.CheckConstraint(
            "status NOT IN ('failed', 'verification_failed') OR error_code IS NOT NULL",
            name="ck_operations_error_state",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_operations_idempotency_key"),
    )
    op.create_index("ix_operations_case_id", "operations", ["case_id"])
    op.create_index("ix_operations_issue_id", "operations", ["issue_id"])

    op.create_table(
        "audit_events",
        sa.Column("audit_event_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "operation_id",
            sa.String(length=100),
            sa.ForeignKey("operations.operation_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column(
            "event_type",
            text_enum(
                "requested",
                "authorized",
                "denied",
                "failed",
                "executed",
                "verified",
                "verification_failed",
                name="audit_event_type",
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column(
            "actor_role",
            text_enum("agent", "operator", "approver", "system", name="audit_actor_role"),
            nullable=False,
        ),
        sa.Column("case_id", sa.String(length=100)),
        sa.Column("issue_id", sa.String(length=100)),
        sa.Column("resource_type", sa.String(length=100)),
        sa.Column("resource_id", sa.String(length=100)),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "operation_id",
            "sequence_number",
            name="uq_audit_events_operation_sequence",
        ),
    )
    op.create_index("ix_audit_events_operation_id", "audit_events", ["operation_id"])
    op.create_index("ix_audit_events_case_id", "audit_events", ["case_id"])
    op.create_index("ix_audit_events_issue_id", "audit_events", ["issue_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_issue_id", table_name="audit_events")
    op.drop_index("ix_audit_events_case_id", table_name="audit_events")
    op.drop_index("ix_audit_events_operation_id", table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_index("ix_operations_issue_id", table_name="operations")
    op.drop_index("ix_operations_case_id", table_name="operations")
    op.drop_table("operations")
