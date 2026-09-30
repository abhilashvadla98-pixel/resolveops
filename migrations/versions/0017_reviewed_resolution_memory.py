"""Add reviewed tenant-scoped resolution memory.

Revision ID: 0017_reviewed_resolution_memory
Revises: 0016_agent_execution_records
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_reviewed_resolution_memory"
down_revision: str | None = "0016_agent_execution_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reviewed_resolution_memory",
        sa.Column("memory_id", sa.String(100), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("issue_type", sa.String(100), nullable=False),
        sa.Column("evidence_pattern", sa.JSON(), nullable=False),
        sa.Column("policy_versions", sa.JSON(), nullable=False),
        sa.Column("approved_resolution", sa.JSON(), nullable=False),
        sa.Column("verification_outcome", sa.String(1000), nullable=False),
        sa.Column("human_feedback_id", sa.String(100), nullable=True),
        sa.Column(
            "review_status",
            sa.Enum(
                "reviewed",
                "retired",
                name="memory_review_status",
                length=32,
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("expires_at > created_at", name="ck_reviewed_memory_expiry"),
    )
    op.create_index(
        "ix_reviewed_resolution_memory_tenant_id",
        "reviewed_resolution_memory",
        ["tenant_id"],
    )
    op.create_index(
        "ix_reviewed_memory_tenant_issue_expiry",
        "reviewed_resolution_memory",
        ["tenant_id", "issue_type", "expires_at"],
    )


def downgrade() -> None:
    op.drop_table("reviewed_resolution_memory")
