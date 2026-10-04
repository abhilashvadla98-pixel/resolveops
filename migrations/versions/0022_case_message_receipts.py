"""Case conversation receipts and idempotent clarification."""

import sqlalchemy as sa
from alembic import op

revision = "0022_case_message_receipts"
down_revision = "0021_payment_obligation_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_messages",
        sa.Column("message_id", sa.String(100), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(100),
            sa.ForeignKey("cases.case_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_message_id", sa.String(100), nullable=False),
        sa.Column("input_return_id", sa.String(100), nullable=True),
        sa.Column("author", sa.String(100), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "source_message_id", name="uq_case_message_source"),
    )
    op.create_index("ix_case_messages_case_id", "case_messages", ["case_id"])


def downgrade() -> None:
    op.drop_table("case_messages")
