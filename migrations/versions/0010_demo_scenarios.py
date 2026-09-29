"""Add the resettable demo scenario catalog.

Revision ID: 0010_demo_scenarios
Revises: 0009_case_intake
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_demo_scenarios"
down_revision: str | None = "0009_case_intake"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "demo_scenarios",
        sa.Column("scenario_id", sa.String(8), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("case_id", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("demo_scenarios")
