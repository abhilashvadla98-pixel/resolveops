from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from resolveops.agents.models import AgentRole, AgentRunStatus, ToolCallStatus
from resolveops.database.base import Base
from resolveops.database.records import UTCDateTime, enum_type


class AgentRunRecord(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_agent_runs_timestamp_order",
        ),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ck_agent_runs_latency"),
        CheckConstraint("tool_call_count >= 0", name="ck_agent_runs_tool_count"),
        Index("ix_agent_runs_workflow_started", "workflow_id", "started_at"),
        Index("ix_agent_runs_tenant_role_started", "tenant_id", "agent_role", "started_at"),
    )

    agent_run_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    workflow_id: Mapped[str] = mapped_column(String(100), index=True)
    agent_role: Mapped[AgentRole] = mapped_column(enum_type(AgentRole, "agent_role"))
    parent_agent_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("agent_runs.agent_run_id", ondelete="SET NULL"), nullable=True
    )
    prompt_version: Mapped[str] = mapped_column(String(100))
    schema_version: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(200))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[AgentRunStatus] = mapped_column(enum_type(AgentRunStatus, "agent_run_status"))
    latency_ms: Mapped[float | None]
    context_hash: Mapped[str] = mapped_column(String(64))
    structured_output: Mapped[dict[str, object] | None] = mapped_column(JSON)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    tool_call_count: Mapped[int] = mapped_column(Integer, default=0)
    error_classification: Mapped[str | None] = mapped_column(String(100))
    trace_id: Mapped[str] = mapped_column(String(100), index=True)

    tool_calls: Mapped[list["AgentToolCallRecord"]] = relationship(
        back_populates="agent_run", cascade="all, delete-orphan"
    )


class AgentToolCallRecord(Base):
    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        CheckConstraint(
            "finished_at IS NULL OR finished_at >= started_at",
            name="ck_agent_tool_calls_timestamp_order",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name="ck_agent_tool_calls_latency"
        ),
        Index("ix_agent_tool_calls_run_started", "agent_run_id", "started_at"),
    )

    tool_call_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    agent_run_id: Mapped[str] = mapped_column(
        ForeignKey("agent_runs.agent_run_id", ondelete="CASCADE"), index=True
    )
    tool_name: Mapped[str] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[ToolCallStatus] = mapped_column(
        enum_type(ToolCallStatus, "agent_tool_call_status")
    )
    latency_ms: Mapped[float | None]
    argument_hash: Mapped[str] = mapped_column(String(64))
    argument_keys: Mapped[list[str]] = mapped_column(JSON)
    result_category: Mapped[str | None] = mapped_column(String(100))
    error_classification: Mapped[str | None] = mapped_column(String(100))

    agent_run: Mapped[AgentRunRecord] = relationship(back_populates="tool_calls")
