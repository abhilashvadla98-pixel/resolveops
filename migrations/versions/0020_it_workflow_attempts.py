"""Retain every IT execution attempt rather than a stale single result."""

from collections.abc import Sequence

from alembic import op

revision: str = "0020_it_workflow_attempts"
down_revision: str | None = "0018_agent_workflow_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_it_workflow_executions_case_id", table_name="it_workflow_executions")
    op.create_index("ix_it_workflow_executions_case_id", "it_workflow_executions", ["case_id"])


def downgrade() -> None:
    # Losing attempt history is not an acceptable implicit downgrade operation.
    bind = op.get_bind()
    duplicates = bind.exec_driver_sql(
        "SELECT case_id FROM it_workflow_executions GROUP BY case_id HAVING COUNT(*) > 1"
    ).first()
    if duplicates is not None:
        raise RuntimeError("Archive IT attempt history before downgrading this migration.")
    op.drop_index("ix_it_workflow_executions_case_id", table_name="it_workflow_executions")
    op.create_index(
        "ix_it_workflow_executions_case_id", "it_workflow_executions", ["case_id"], unique=True
    )
