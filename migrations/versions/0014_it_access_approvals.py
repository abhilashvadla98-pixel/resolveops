"""Add durable IT access approval decisions.

Revision ID: 0014_it_access_approvals
Revises: 0013_case_queue_updated_index
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_it_access_approvals"
down_revision: str | None = "0013_case_queue_updated_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "it_access_approval_decisions",
        sa.Column("approval_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(length=100),
            sa.ForeignKey("it_access_cases.case_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "access_request_id",
            sa.String(length=100),
            sa.ForeignKey("it_access_requests.access_request_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "decision",
            sa.Enum(
                "approve",
                "reject",
                name="it_access_approval_decision",
                length=32,
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("decided_by", sa.String(length=100), nullable=False),
        sa.Column(
            "manager_employee_id",
            sa.String(length=100),
            sa.ForeignKey("employees.employee_id"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("it_access_approval_decisions")
