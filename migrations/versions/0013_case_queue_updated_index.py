"""Index the primary case queue ordering.

Revision ID: 0013_case_queue_updated_index
Revises: 0012_operator_feedback
Create Date: 2026-09-29
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013_case_queue_updated_index"
down_revision: str | None = "0012_operator_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_cases_updated_at_desc", "cases", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_cases_updated_at_desc", table_name="cases")
