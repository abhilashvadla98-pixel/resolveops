"""Add durable agent workflow jobs and event stream.

Revision ID: 0018_agent_workflow_jobs
Revises: 0017_reviewed_resolution_memory
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_agent_workflow_jobs"
down_revision: str | None = "0017_reviewed_resolution_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    job_status = sa.Enum(
        "pending",
        "running",
        "completed",
        "retrying",
        "failed",
        "dead_letter",
        name="agent_job_status",
        length=32,
        native_enum=False,
        create_constraint=True,
    )
    event_status = sa.Enum(
        "pending",
        "running",
        "completed",
        "retrying",
        "failed",
        "dead_letter",
        name="agent_job_event_status",
        length=32,
        native_enum=False,
        create_constraint=True,
    )
    op.create_table(
        "agent_workflow_jobs",
        sa.Column("job_id", sa.String(100), primary_key=True),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("workflow_id", sa.String(100), nullable=False),
        sa.Column("case_id", sa.String(100), nullable=False),
        sa.Column(
            "domain",
            sa.Enum(
                "customer_operations",
                "employee_it",
                name="agent_job_domain",
                length=32,
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("objective", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("status", job_status, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("worker_id", sa.String(100)),
        sa.Column("result", sa.JSON()),
        sa.Column("error_classification", sa.String(100)),
        sa.CheckConstraint("attempts >= 0", name="ck_agent_jobs_attempts"),
        sa.CheckConstraint("max_attempts >= 1", name="ck_agent_jobs_max_attempts"),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_agent_jobs_tenant_key"),
    )
    op.create_index("ix_agent_workflow_jobs_tenant_id", "agent_workflow_jobs", ["tenant_id"])
    op.create_index("ix_agent_workflow_jobs_workflow_id", "agent_workflow_jobs", ["workflow_id"])
    op.create_index("ix_agent_workflow_jobs_case_id", "agent_workflow_jobs", ["case_id"])
    op.create_index(
        "ix_agent_jobs_claim",
        "agent_workflow_jobs",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_agent_jobs_tenant_created",
        "agent_workflow_jobs",
        ["tenant_id", "created_at"],
    )
    op.create_table(
        "agent_job_events",
        sa.Column("event_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(100), nullable=False),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "queued",
                "claimed",
                "agent_started",
                "agent_completed",
                "agent_failed",
                "retry_scheduled",
                "completed",
                "failed",
                "dead_lettered",
                name="agent_job_event_type",
                length=32,
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("status", event_status, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["agent_workflow_jobs.job_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_agent_job_events_job_id", "agent_job_events", ["job_id"])
    op.create_index("ix_agent_job_events_tenant_id", "agent_job_events", ["tenant_id"])
    op.create_index("ix_agent_job_events_job_event", "agent_job_events", ["job_id", "event_id"])


def downgrade() -> None:
    op.drop_table("agent_job_events")
    op.drop_table("agent_workflow_jobs")
