"""Add authenticated inbound event records and ordering cursors.

Revision ID: 0007_event_ingestion
Revises: 0006_operation_reliability
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_event_ingestion"
down_revision: str | None = "0006_operation_reliability"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def text_enum(*values: str, name: str, length: int = 32) -> sa.Enum:
    return sa.Enum(
        *values,
        name=name,
        length=length,
        native_enum=False,
        create_constraint=True,
    )


def upgrade() -> None:
    op.create_table(
        "inbound_events",
        sa.Column("event_id", sa.String(length=100), primary_key=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=1000), nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            text_enum(
                "processed",
                "ignored_stale",
                "rejected",
                name="inbound_event_status",
            ),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_id", sa.String(length=100), nullable=False),
        sa.Column("provider_reference", sa.String(length=100), nullable=False),
        sa.Column("error_code", sa.String(length=100)),
        sa.Column("error_message", sa.Text()),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "processed_at >= received_at",
            name="ck_inbound_events_processing_order",
        ),
    )
    op.create_index("ix_inbound_events_event_type", "inbound_events", ["event_type"])
    op.create_index("ix_inbound_events_occurred_at", "inbound_events", ["occurred_at"])
    op.create_index("ix_inbound_events_resource_id", "inbound_events", ["resource_id"])

    op.create_table(
        "resource_event_cursors",
        sa.Column("resource_type", sa.String(length=100), primary_key=True),
        sa.Column(
            "resource_id",
            sa.String(length=100),
            sa.ForeignKey("refunds.refund_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "last_event_id",
            sa.String(length=100),
            sa.ForeignKey("inbound_events.event_id", ondelete="RESTRICT"),
            nullable=False,
            unique=True,
        ),
        sa.Column("last_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_reference", sa.String(length=100), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("resource_event_cursors")
    op.drop_index("ix_inbound_events_resource_id", table_name="inbound_events")
    op.drop_index("ix_inbound_events_occurred_at", table_name="inbound_events")
    op.drop_index("ix_inbound_events_event_type", table_name="inbound_events")
    op.drop_table("inbound_events")
