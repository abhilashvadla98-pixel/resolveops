"""Expand workflow events into a visible action lifecycle.

Revision ID: 0011_workflow_action_timeline
Revises: 0010_demo_scenarios
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_workflow_action_timeline"
down_revision: str | None = "0010_demo_scenarios"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BASE_EVENT_TYPES = (
    "started",
    "approval_requested",
    "approval_approved",
    "approval_rejected",
    "completed",
    "escalated",
    "failed",
)

ACTION_EVENT_TYPES = (
    "customer_verified",
    "order_loaded",
    "payment_evidence_loaded",
    "return_evidence_loaded",
    "policy_retrieved",
    "advisory_assessed",
    "decision_recorded",
    "safety_gate_evaluated",
    "action_executed",
    "action_verified",
    "final_response_created",
)


def event_enum(*values: str) -> sa.Enum:
    return sa.Enum(
        *values,
        name="workflow_event_type",
        length=32,
        native_enum=False,
        create_constraint=True,
    )


def upgrade() -> None:
    with op.batch_alter_table("workflow_events", recreate="always") as batch:
        batch.alter_column(
            "event_type",
            existing_type=event_enum(*BASE_EVENT_TYPES),
            type_=event_enum(*BASE_EVENT_TYPES, *ACTION_EVENT_TYPES),
            existing_nullable=False,
        )


def downgrade() -> None:
    workflow_events = sa.table(
        "workflow_events",
        sa.column("event_type", sa.String(length=32)),
    )
    op.execute(
        workflow_events.update()
        .where(workflow_events.c.event_type.in_(ACTION_EVENT_TYPES))
        .values(event_type="completed")
    )
    with op.batch_alter_table("workflow_events", recreate="always") as batch:
        batch.alter_column(
            "event_type",
            existing_type=event_enum(*BASE_EVENT_TYPES, *ACTION_EVENT_TYPES),
            type_=event_enum(*BASE_EVENT_TYPES),
            existing_nullable=False,
        )
