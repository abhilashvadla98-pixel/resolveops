from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from resolveops.database.base import Base
from resolveops.database.records import UTCDateTime, enum_type
from resolveops.operations.models import (
    ActorRole,
    AuditEventType,
    OperationStatus,
    OperationType,
    ReliabilityEventType,
)


class OperationRecord(Base):
    __tablename__ = "operations"
    __table_args__ = (
        CheckConstraint("updated_at >= created_at", name="ck_operations_timestamp_order"),
        CheckConstraint(
            "status NOT IN ('executed', 'completed') OR result_resource_id IS NOT NULL",
            name="ck_operations_result_state",
        ),
        CheckConstraint(
            "status NOT IN ('failed', 'verification_failed') OR error_code IS NOT NULL",
            name="ck_operations_error_state",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_operations_attempt_count"),
        CheckConstraint(
            "verification_attempt_count >= 0",
            name="ck_operations_verification_attempt_count",
        ),
        CheckConstraint("max_attempts > 0", name="ck_operations_max_attempts"),
    )

    operation_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    operation_type: Mapped[OperationType] = mapped_column(
        enum_type(OperationType, "operation_type")
    )
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[OperationStatus] = mapped_column(enum_type(OperationStatus, "operation_status"))
    actor_id: Mapped[str] = mapped_column(String(100))
    actor_role: Mapped[ActorRole] = mapped_column(enum_type(ActorRole, "actor_role"))
    case_id: Mapped[str | None] = mapped_column(String(100), index=True)
    issue_id: Mapped[str | None] = mapped_column(String(100), index=True)
    result_resource_id: Mapped[str | None] = mapped_column(String(100))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    verification_attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    last_error_retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())

    audit_events: Mapped[list["AuditEventRecord"]] = relationship(
        back_populates="operation",
        cascade="all, delete-orphan",
        order_by="AuditEventRecord.sequence_number",
    )
    reliability_events: Mapped[list["ReliabilityEventRecord"]] = relationship(
        back_populates="operation",
        cascade="all, delete-orphan",
        order_by="ReliabilityEventRecord.sequence_number",
    )


class AuditEventRecord(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        UniqueConstraint(
            "operation_id", "sequence_number", name="uq_audit_events_operation_sequence"
        ),
    )

    audit_event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    operation_id: Mapped[str] = mapped_column(
        ForeignKey("operations.operation_id", ondelete="CASCADE"), index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[AuditEventType] = mapped_column(
        enum_type(AuditEventType, "audit_event_type")
    )
    actor_id: Mapped[str] = mapped_column(String(100))
    actor_role: Mapped[ActorRole] = mapped_column(enum_type(ActorRole, "audit_actor_role"))
    case_id: Mapped[str | None] = mapped_column(String(100), index=True)
    issue_id: Mapped[str | None] = mapped_column(String(100), index=True)
    resource_type: Mapped[str | None] = mapped_column(String(100))
    resource_id: Mapped[str | None] = mapped_column(String(100))
    details: Mapped[dict[str, object]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime())

    operation: Mapped[OperationRecord] = relationship(back_populates="audit_events")


class ReliabilityEventRecord(Base):
    __tablename__ = "operation_reliability_events"
    __table_args__ = (
        CheckConstraint(
            "attempt_number IS NULL OR attempt_number > 0",
            name="ck_reliability_events_attempt_number",
        ),
        UniqueConstraint(
            "operation_id",
            "sequence_number",
            name="uq_reliability_events_operation_sequence",
        ),
    )

    reliability_event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    operation_id: Mapped[str] = mapped_column(
        ForeignKey("operations.operation_id", ondelete="CASCADE"), index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[ReliabilityEventType] = mapped_column(
        enum_type(ReliabilityEventType, "reliability_event_type")
    )
    attempt_number: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict[str, object]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime())

    operation: Mapped[OperationRecord] = relationship(back_populates="reliability_events")
