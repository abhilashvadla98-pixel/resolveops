"""Explicit payment obligation evidence; old unknown records remain untrusted."""

import sqlalchemy as sa
from alembic import op

revision = "0021_payment_obligation_evidence"
down_revision = "0020_it_workflow_attempts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("payments") as batch:
        batch.add_column(sa.Column("obligation_id", sa.String(100), nullable=True))
        batch.add_column(sa.Column("obligation_amount", sa.Numeric(18, 2), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("payments") as batch:
        batch.drop_column("obligation_amount")
        batch.drop_column("obligation_id")
