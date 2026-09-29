"""Persist bounded agent runs and read-only tool calls.

Revision ID: 0016_agent_execution_records
Revises: 0015_it_workflow_executions
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_agent_execution_records"
down_revision: str | None = "0015_it_workflow_executions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def text_enum(*values: str, name: str) -> sa.Enum:
    return sa.Enum(*values, name=name, length=32, native_enum=False, create_constraint=True)


def upgrade() -> None:
    op.create_table(
        "agent_runs",
        sa.Column("agent_run_id", sa.String(100), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("workflow_id", sa.String(100), nullable=False),
        sa.Column(
            "agent_role",
            text_enum(
                "supervisor", "investigation", "policy", "resolution", "critic", name="agent_role"
            ),
            nullable=False,
        ),
        sa.Column(
            "parent_agent_run_id",
            sa.String(100),
            sa.ForeignKey("agent_runs.agent_run_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("prompt_version", sa.String(100), nullable=False),
        sa.Column("schema_version", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            text_enum("running", "completed", "failed", "budget_exceeded", name="agent_run_status"),
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Double(), nullable=True),
        sa.Column("context_hash", sa.String(64), nullable=False),
        sa.Column("structured_output", sa.JSON(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("tool_call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_classification", sa.String(100), nullable=True),
        sa.Column("trace_id", sa.String(100), nullable=False),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at", name="ck_agent_runs_timestamp_order"
        ),
        sa.CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ck_agent_runs_latency"),
        sa.CheckConstraint("tool_call_count >= 0", name="ck_agent_runs_tool_count"),
    )
    op.create_index("ix_agent_runs_tenant_id", "agent_runs", ["tenant_id"])
    op.create_index("ix_agent_runs_workflow_id", "agent_runs", ["workflow_id"])
    op.create_index("ix_agent_runs_trace_id", "agent_runs", ["trace_id"])
    op.create_index("ix_agent_runs_workflow_started", "agent_runs", ["workflow_id", "started_at"])
    op.create_index(
        "ix_agent_runs_tenant_role_started", "agent_runs", ["tenant_id", "agent_role", "started_at"]
    )

    op.create_table(
        "agent_tool_calls",
        sa.Column("tool_call_id", sa.String(100), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column(
            "agent_run_id",
            sa.String(100),
            sa.ForeignKey("agent_runs.agent_run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            text_enum("started", "completed", "failed", "denied", name="agent_tool_call_status"),
            nullable=False,
        ),
        sa.Column("latency_ms", sa.Double(), nullable=True),
        sa.Column("argument_hash", sa.String(64), nullable=False),
        sa.Column("argument_keys", sa.JSON(), nullable=False),
        sa.Column("result_category", sa.String(100), nullable=True),
        sa.Column("error_classification", sa.String(100), nullable=True),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_agent_tool_calls_timestamp_order",
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name="ck_agent_tool_calls_latency"
        ),
    )
    op.create_index("ix_agent_tool_calls_tenant_id", "agent_tool_calls", ["tenant_id"])
    op.create_index("ix_agent_tool_calls_agent_run_id", "agent_tool_calls", ["agent_run_id"])
    op.create_index(
        "ix_agent_tool_calls_run_started", "agent_tool_calls", ["agent_run_id", "started_at"]
    )


def downgrade() -> None:
    op.drop_table("agent_tool_calls")
    op.drop_table("agent_runs")
