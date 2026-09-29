from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from resolveops.database.base import Base
from resolveops.database.records import UTCDateTime, enum_type
from resolveops.operations.models import ActorRole, OperationType
from resolveops.workflows.models import (
    ApprovalStatus,
    WorkflowEventType,
    WorkflowLifecycleStatus,
    WorkflowOutcome,
)


class WorkflowRunRecord(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        CheckConstraint("updated_at >= created_at", name="ck_workflow_runs_timestamp_order"),
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= created_at",
            name="ck_workflow_runs_completion_order",
        ),
        CheckConstraint(
            "status NOT IN ('completed', 'escalated', 'failed') OR completed_at IS NOT NULL",
            name="ck_workflow_runs_terminal_time",
        ),
    )

    workflow_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    thread_id: Mapped[str] = mapped_column(String(100), unique=True)
    case_id: Mapped[str] = mapped_column(String(100), index=True)
    issue_id: Mapped[str] = mapped_column(String(100), index=True)
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[WorkflowLifecycleStatus] = mapped_column(
        enum_type(WorkflowLifecycleStatus, "workflow_lifecycle_status")
    )
    outcome: Mapped[WorkflowOutcome | None] = mapped_column(
        enum_type(WorkflowOutcome, "workflow_run_outcome"), nullable=True
    )
    requested_by: Mapped[str] = mapped_column(String(100))
    requested_role: Mapped[ActorRole] = mapped_column(
        enum_type(ActorRole, "workflow_requested_role")
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    approvals: Mapped[list["WorkflowApprovalRecord"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowApprovalRecord.requested_at",
    )
    events: Mapped[list["WorkflowEventRecord"]] = relationship(
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowEventRecord.sequence_number",
    )


class WorkflowApprovalRecord(Base):
    __tablename__ = "workflow_approvals"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_workflow_approvals_positive_amount"),
        CheckConstraint(
            "length(currency) = 3 AND currency = upper(currency)",
            name="ck_workflow_approvals_currency",
        ),
        CheckConstraint(
            "(status = 'pending' AND decided_by IS NULL AND decided_role IS NULL "
            "AND decided_at IS NULL) OR "
            "(status != 'pending' AND decided_by IS NOT NULL AND decided_role IS NOT NULL "
            "AND decided_at IS NOT NULL)",
            name="ck_workflow_approvals_decision_state",
        ),
        UniqueConstraint("workflow_id", "operation_type", name="uq_workflow_approvals_action"),
    )

    approval_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.workflow_id", ondelete="CASCADE"), index=True
    )
    operation_type: Mapped[OperationType] = mapped_column(
        enum_type(OperationType, "workflow_approval_operation_type")
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        enum_type(ApprovalStatus, "workflow_approval_status")
    )
    case_id: Mapped[str] = mapped_column(String(100))
    issue_id: Mapped[str] = mapped_column(String(100))
    payment_id: Mapped[str] = mapped_column(String(100))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    reason: Mapped[str] = mapped_column(String(1000))
    requested_by: Mapped[str] = mapped_column(String(100))
    requested_role: Mapped[ActorRole] = mapped_column(
        enum_type(ActorRole, "workflow_approval_requested_role")
    )
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime())
    decided_by: Mapped[str | None] = mapped_column(String(100))
    decided_role: Mapped[ActorRole | None] = mapped_column(
        enum_type(ActorRole, "workflow_approval_decided_role"), nullable=True
    )
    decision_note: Mapped[str | None] = mapped_column(String(1000))
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    workflow: Mapped[WorkflowRunRecord] = relationship(back_populates="approvals")


class WorkflowEventRecord(Base):
    __tablename__ = "workflow_events"
    __table_args__ = (
        UniqueConstraint("workflow_id", "sequence_number", name="uq_workflow_events_sequence"),
    )

    event_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.workflow_id", ondelete="CASCADE"), index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[WorkflowEventType] = mapped_column(
        enum_type(WorkflowEventType, "workflow_event_type")
    )
    actor_id: Mapped[str | None] = mapped_column(String(100))
    actor_role: Mapped[ActorRole | None] = mapped_column(
        enum_type(ActorRole, "workflow_event_actor_role"), nullable=True
    )
    details: Mapped[dict[str, object]] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime())

    workflow: Mapped[WorkflowRunRecord] = relationship(back_populates="events")
