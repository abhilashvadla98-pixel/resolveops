"""Add operation retry, recovery, and reliability records.

Revision ID: 0006_operation_reliability
Revises: 0005_durable_workflows
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_operation_reliability"
down_revision: str | None = "0005_durable_workflows"
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
    with op.batch_alter_table("operations") as batch:
        batch.add_column(
            sa.Column(
                "attempt_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "verification_attempt_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            )
        )
        batch.add_column(
            sa.Column(
                "max_attempts",
                sa.Integer(),
                nullable=False,
                server_default="3",
            )
        )
        batch.add_column(
            sa.Column(
                "last_error_retryable",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(sa.Column("last_attempt_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
        batch.create_check_constraint("ck_operations_attempt_count", "attempt_count >= 0")
        batch.create_check_constraint(
            "ck_operations_verification_attempt_count",
            "verification_attempt_count >= 0",
        )
        batch.create_check_constraint("ck_operations_max_attempts", "max_attempts > 0")

    op.create_table(
        "operation_reliability_events",
        sa.Column("reliability_event_id", sa.String(length=100), primary_key=True),
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
                "attempt_started",
                "retry_scheduled",
                "attempt_succeeded",
                "lease_recovered",
                "verification_attempted",
                "verification_retry_scheduled",
                "recovery_verified",
                "compensation_required",
                "manual_review_required",
                name="reliability_event_type",
            ),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer()),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "attempt_number IS NULL OR attempt_number > 0",
            name="ck_reliability_events_attempt_number",
        ),
        sa.UniqueConstraint(
            "operation_id",
            "sequence_number",
            name="uq_reliability_events_operation_sequence",
        ),
    )
    op.create_index(
        "ix_operation_reliability_events_operation_id",
        "operation_reliability_events",
        ["operation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_operation_reliability_events_operation_id",
        table_name="operation_reliability_events",
    )
    op.drop_table("operation_reliability_events")
    with op.batch_alter_table("operations") as batch:
        batch.drop_constraint("ck_operations_max_attempts", type_="check")
        batch.drop_constraint("ck_operations_verification_attempt_count", type_="check")
        batch.drop_constraint("ck_operations_attempt_count", type_="check")
        batch.drop_column("lease_expires_at")
        batch.drop_column("next_attempt_at")
        batch.drop_column("last_attempt_at")
        batch.drop_column("last_error_retryable")
        batch.drop_column("max_attempts")
        batch.drop_column("verification_attempt_count")
        batch.drop_column("attempt_count")
