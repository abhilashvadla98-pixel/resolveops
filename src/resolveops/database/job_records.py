from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from resolveops.agents.models import AgentDomain
from resolveops.database.base import Base
from resolveops.database.records import UTCDateTime, enum_type
from resolveops.jobs.models import AgentJobEventType, AgentJobStatus


class AgentWorkflowJobRecord(Base):
    __tablename__ = "agent_workflow_jobs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_agent_jobs_tenant_key"),
        CheckConstraint("attempts >= 0", name="ck_agent_jobs_attempts"),
        CheckConstraint("max_attempts >= 1", name="ck_agent_jobs_max_attempts"),
        Index("ix_agent_jobs_claim", "status", "available_at", "created_at"),
        Index("ix_agent_jobs_tenant_created", "tenant_id", "created_at"),
    )

    job_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    workflow_id: Mapped[str] = mapped_column(String(100), index=True)
    case_id: Mapped[str] = mapped_column(String(100), index=True)
    domain: Mapped[AgentDomain] = mapped_column(enum_type(AgentDomain, "agent_job_domain"))
    objective: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    status: Mapped[AgentJobStatus] = mapped_column(enum_type(AgentJobStatus, "agent_job_status"))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    available_at: Mapped[datetime] = mapped_column(UTCDateTime())
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    worker_id: Mapped[str | None] = mapped_column(String(100))
    result: Mapped[dict[str, object] | None] = mapped_column(JSON)
    error_classification: Mapped[str | None] = mapped_column(String(100))


class AgentJobEventRecord(Base):
    __tablename__ = "agent_job_events"
    __table_args__ = (Index("ix_agent_job_events_job_event", "job_id", "event_id"),)

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("agent_workflow_jobs.job_id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    event_type: Mapped[AgentJobEventType] = mapped_column(
        enum_type(AgentJobEventType, "agent_job_event_type")
    )
    status: Mapped[AgentJobStatus] = mapped_column(
        enum_type(AgentJobStatus, "agent_job_event_status")
    )
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime())
    details: Mapped[dict[str, str]] = mapped_column(JSON)
