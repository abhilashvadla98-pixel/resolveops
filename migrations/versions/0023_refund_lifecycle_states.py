"""Persist pending refunds separately from settled money movement.

Downgrade refuses to erase states that the previous schema cannot represent.
"""

import sqlalchemy as sa
from alembic import op

revision = "0023_refund_lifecycle_states"
down_revision = "0022_case_message_receipts"
branch_labels = None
depends_on = None

OLD_STATUSES = ("running", "waiting_approval", "completed", "escalated", "failed")
OLD_OUTCOMES = ("action_verified", "waiting_external", "needs_review")
NEW_OUTCOMES = ("refund_submitted", "refund_settled", "no_action_required")
OLD_EVENTS = (
    "started",
    "approval_requested",
    "approval_approved",
    "approval_rejected",
    "completed",
    "escalated",
    "failed",
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


def enum(name: str, values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name=name, length=32, native_enum=False, create_constraint=True)


def change(*, upgrading: bool) -> None:
    status = (OLD_STATUSES, (*OLD_STATUSES, "waiting_external"))
    outcome = (OLD_OUTCOMES, (*OLD_OUTCOMES, *NEW_OUTCOMES))
    events = (OLD_EVENTS, (*OLD_EVENTS, "refund_status_changed"))
    before, after = (0, 1) if upgrading else (1, 0)
    with op.batch_alter_table("workflow_runs") as batch:
        batch.alter_column(
            "status",
            existing_type=enum("workflow_lifecycle_status", status[before]),
            type_=enum("workflow_lifecycle_status", status[after]),
            existing_nullable=False,
        )
        batch.alter_column(
            "outcome",
            existing_type=enum("workflow_run_outcome", outcome[before]),
            type_=enum("workflow_run_outcome", outcome[after]),
            existing_nullable=True,
        )
    with op.batch_alter_table("workflow_events") as batch:
        batch.alter_column(
            "event_type",
            existing_type=enum("workflow_event_type", events[before]),
            type_=enum("workflow_event_type", events[after]),
            existing_nullable=False,
        )


def upgrade() -> None:
    change(upgrading=True)


def downgrade() -> None:
    connection = op.get_bind()
    incompatible = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM workflow_runs WHERE status = 'waiting_external' "
            "OR outcome IN ('refund_submitted', 'refund_settled', 'no_action_required')"
        )
    ).scalar_one()
    new_events = connection.execute(
        sa.text("SELECT COUNT(*) FROM workflow_events WHERE event_type = 'refund_status_changed'")
    ).scalar_one()
    if incompatible or new_events:
        raise RuntimeError("Cannot downgrade: refund lifecycle history requires this schema.")
    change(upgrading=False)
