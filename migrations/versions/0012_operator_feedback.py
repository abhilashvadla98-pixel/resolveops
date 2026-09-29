"""Add structured operator feedback.

Revision ID: 0012_operator_feedback
Revises: 0011_workflow_action_timeline
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_operator_feedback"
down_revision: str | None = "0011_workflow_action_timeline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operator_feedback",
        sa.Column("feedback_id", sa.String(length=100), primary_key=True),
        sa.Column("case_id", sa.String(length=100), sa.ForeignKey("cases.case_id"), nullable=False),
        sa.Column("workflow_id", sa.String(length=100)),
        sa.Column("trace_id", sa.String(length=100)),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("original_value", sa.JSON(), nullable=False),
        sa.Column("corrected_value", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("operator_id", sa.String(length=100), nullable=False),
        sa.Column("model_provider", sa.String(length=100)),
        sa.Column("model_name", sa.String(length=200)),
        sa.Column("prompt_version", sa.String(length=100)),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.String(length=100)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_note", sa.Text()),
        sa.Column("dataset_example_id", sa.String(length=100), unique=True),
        sa.CheckConstraint(
            "kind IN ('classification_correction','recommendation_rejected','approval_rejected','resolution_changed','customer_response_edited','evidence_insufficient')",
            name="feedback_kind",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending','reviewed','rejected','promoted')",
            name="feedback_review_status",
        ),
        sa.CheckConstraint(
            "(review_status = 'pending' AND reviewed_by IS NULL AND reviewed_at IS NULL) OR (review_status != 'pending' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_operator_feedback_review_state",
        ),
        sa.CheckConstraint(
            "review_status != 'promoted' OR dataset_example_id IS NOT NULL",
            name="ck_operator_feedback_promoted_example",
        ),
    )
    for column in (
        "case_id",
        "workflow_id",
        "trace_id",
        "operator_id",
        "review_status",
        "created_at",
    ):
        op.create_index(f"ix_operator_feedback_{column}", "operator_feedback", [column])


def downgrade() -> None:
    op.drop_table("operator_feedback")
