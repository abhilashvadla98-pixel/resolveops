"""Persist natural-language case intake.

Revision ID: 0009_case_intake
Revises: 0008_employee_it_domain
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_case_intake"
down_revision: str | None = "0008_employee_it_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("cases") as batch:
        batch.add_column(sa.Column("complaint_text", sa.Text(), nullable=True))
        batch.add_column(sa.Column("intake_status", sa.String(32), nullable=True))
        batch.add_column(sa.Column("intake_summary", sa.Text(), nullable=True))
        batch.create_check_constraint(
            "case_intake_status",
            "intake_status IS NULL OR intake_status IN "
            "('classified', 'needs_clarification', 'unsupported', 'rejected')",
        )
    with op.batch_alter_table("case_issues") as batch:
        batch.add_column(sa.Column("classification_confidence", sa.Numeric(5, 4), nullable=True))
        batch.create_check_constraint(
            "ck_case_issue_classification_confidence",
            "classification_confidence IS NULL OR "
            "(classification_confidence >= 0 AND classification_confidence <= 1)",
        )


def downgrade() -> None:
    with op.batch_alter_table("case_issues") as batch:
        batch.drop_constraint("ck_case_issue_classification_confidence", type_="check")
        batch.drop_column("classification_confidence")
    with op.batch_alter_table("cases") as batch:
        batch.drop_constraint("case_intake_status", type_="check")
        batch.drop_column("intake_summary")
        batch.drop_column("intake_status")
        batch.drop_column("complaint_text")
