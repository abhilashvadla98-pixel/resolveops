"""Persist Employee IT agent execution provenance."""

import json

import sqlalchemy as sa
from alembic import op

revision = "0025_employee_it_agent_execution"
down_revision = "0024_customer_issue_expansion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("it_workflow_executions") as batch:
        batch.add_column(
            sa.Column(
                "execution_mode",
                sa.String(length=30),
                nullable=False,
                server_default="rules_only",
            )
        )
        batch.add_column(
            sa.Column(
                "agent_run_ids",
                sa.JSON(),
                nullable=False,
                server_default=json.dumps([]),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("it_workflow_executions") as batch:
        batch.drop_column("agent_run_ids")
        batch.drop_column("execution_mode")
