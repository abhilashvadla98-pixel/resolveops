from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from resolveops.database.base import Base
from resolveops.database.records import UTCDateTime, enum_type
from resolveops.events.models import InboundEventStatus


class InboundEventRecord(Base):
    __tablename__ = "inbound_events"
    __table_args__ = (
        CheckConstraint(
            "processed_at >= received_at",
            name="ck_inbound_events_processing_order",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    source: Mapped[str] = mapped_column(String(1000))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, object]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    status: Mapped[InboundEventStatus] = mapped_column(
        enum_type(InboundEventStatus, "inbound_event_status")
    )
    resource_type: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str] = mapped_column(String(100), index=True)
    provider_reference: Mapped[str] = mapped_column(String(100))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime())
    processed_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ResourceEventCursorRecord(Base):
    __tablename__ = "resource_event_cursors"

    resource_type: Mapped[str] = mapped_column(String(100), primary_key=True)
    resource_id: Mapped[str] = mapped_column(
        ForeignKey("refunds.refund_id", ondelete="CASCADE"), primary_key=True
    )
    last_event_id: Mapped[str] = mapped_column(
        ForeignKey("inbound_events.event_id", ondelete="RESTRICT"), unique=True
    )
    last_occurred_at: Mapped[datetime] = mapped_column(UTCDateTime())
    provider_reference: Mapped[str] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
