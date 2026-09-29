import json
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from resolveops.agents.models import (
    AgentInvocationRecord,
    AgentRole,
    AgentRunStatus,
    ToolCallRecord,
    ToolCallStatus,
)
from resolveops.database.agent_records import AgentRunRecord, AgentToolCallRecord

MAX_STRUCTURED_OUTPUT_BYTES = 65_536


def safe_context_hash(context: BaseModel | dict[str, object]) -> str:
    payload = context.model_dump(mode="json") if isinstance(context, BaseModel) else context
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


def safe_argument_metadata(arguments: dict[str, object]) -> tuple[str, list[str]]:
    encoded = json.dumps(arguments, sort_keys=True, default=str).encode("utf-8")
    return sha256(encoded).hexdigest(), sorted(arguments)


class AgentRunStore:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock or (lambda: datetime.now(UTC))

    def start(
        self,
        *,
        tenant_id: str,
        workflow_id: str,
        role: AgentRole,
        prompt_version: str,
        schema_version: str,
        provider: str,
        model: str,
        context_hash: str,
        trace_id: str,
        parent_agent_run_id: str | None = None,
    ) -> AgentInvocationRecord:
        record = AgentRunRecord(
            agent_run_id=f"ARUN-{uuid4().hex[:20]}",
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            agent_role=role,
            parent_agent_run_id=parent_agent_run_id,
            prompt_version=prompt_version,
            schema_version=schema_version,
            provider=provider,
            model=model,
            started_at=self.clock(),
            finished_at=None,
            status=AgentRunStatus.RUNNING,
            latency_ms=None,
            context_hash=context_hash,
            structured_output=None,
            input_tokens=None,
            output_tokens=None,
            tool_call_count=0,
            error_classification=None,
            trace_id=trace_id,
        )
        with self.session_factory.begin() as session:
            session.add(record)
        return self._agent_model(record)

    def finish(
        self,
        agent_run_id: str,
        *,
        output: BaseModel | dict[str, object],
        input_tokens: int | None,
        output_tokens: int | None,
        status: AgentRunStatus = AgentRunStatus.COMPLETED,
        error_classification: str | None = None,
    ) -> AgentInvocationRecord:
        payload = output.model_dump(mode="json") if isinstance(output, BaseModel) else output
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        if len(encoded) > MAX_STRUCTURED_OUTPUT_BYTES:
            raise ValueError("agent structured output exceeds persistence limit")
        with self.session_factory.begin() as session:
            record = session.get(AgentRunRecord, agent_run_id)
            if record is None:
                raise KeyError(f"agent run {agent_run_id} does not exist")
            if record.status != AgentRunStatus.RUNNING:
                raise ValueError("agent run is already terminal")
            finished_at = self.clock()
            record.finished_at = finished_at
            record.latency_ms = max((finished_at - record.started_at).total_seconds() * 1000, 0)
            record.structured_output = payload
            record.input_tokens = input_tokens
            record.output_tokens = output_tokens
            record.status = status
            record.error_classification = error_classification
            session.flush()
            return self._agent_model(record)

    def list_for_workflow(self, workflow_id: str) -> list[AgentInvocationRecord]:
        with self.session_factory() as session:
            records = session.scalars(
                select(AgentRunRecord)
                .where(AgentRunRecord.workflow_id == workflow_id)
                .order_by(AgentRunRecord.started_at, AgentRunRecord.agent_run_id)
            ).all()
            return [self._agent_model(item) for item in records]

    def start_tool_call(
        self,
        *,
        tenant_id: str,
        agent_run_id: str,
        tool_name: str,
        arguments: dict[str, object],
    ) -> ToolCallRecord:
        argument_hash, argument_keys = safe_argument_metadata(arguments)
        record = AgentToolCallRecord(
            tool_call_id=f"TCALL-{uuid4().hex[:20]}",
            tenant_id=tenant_id,
            agent_run_id=agent_run_id,
            tool_name=tool_name,
            started_at=self.clock(),
            finished_at=None,
            status=ToolCallStatus.STARTED,
            latency_ms=None,
            argument_hash=argument_hash,
            argument_keys=argument_keys,
            result_category=None,
            error_classification=None,
        )
        with self.session_factory.begin() as session:
            parent = session.get(AgentRunRecord, agent_run_id)
            if parent is None or parent.status != AgentRunStatus.RUNNING:
                raise ValueError("tool call requires a running agent run")
            parent.tool_call_count += 1
            session.add(record)
        return self._tool_model(record)

    def finish_tool_call(
        self,
        tool_call_id: str,
        *,
        status: ToolCallStatus,
        result_category: str | None = None,
        error_classification: str | None = None,
    ) -> ToolCallRecord:
        with self.session_factory.begin() as session:
            record = session.get(AgentToolCallRecord, tool_call_id)
            if record is None:
                raise KeyError(f"tool call {tool_call_id} does not exist")
            if record.status != ToolCallStatus.STARTED:
                raise ValueError("tool call is already terminal")
            finished_at = self.clock()
            record.finished_at = finished_at
            record.latency_ms = max((finished_at - record.started_at).total_seconds() * 1000, 0)
            record.status = status
            record.result_category = result_category
            record.error_classification = error_classification
            session.flush()
            return self._tool_model(record)

    @staticmethod
    def _agent_model(record: AgentRunRecord) -> AgentInvocationRecord:
        return AgentInvocationRecord(
            agent_run_id=record.agent_run_id,
            tenant_id=record.tenant_id,
            workflow_id=record.workflow_id,
            role=record.agent_role,
            parent_agent_run_id=record.parent_agent_run_id,
            prompt_version=record.prompt_version,
            schema_version=record.schema_version,
            provider=record.provider,
            model=record.model,
            started_at=record.started_at,
            finished_at=record.finished_at,
            status=record.status,
            latency_ms=record.latency_ms,
            context_hash=record.context_hash,
            structured_output=record.structured_output,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
            tool_call_count=record.tool_call_count,
            error_classification=record.error_classification,
            trace_id=record.trace_id,
        )

    @staticmethod
    def _tool_model(record: AgentToolCallRecord) -> ToolCallRecord:
        return ToolCallRecord(
            tool_call_id=record.tool_call_id,
            tenant_id=record.tenant_id,
            agent_run_id=record.agent_run_id,
            tool_name=record.tool_name,
            started_at=record.started_at,
            finished_at=record.finished_at,
            status=record.status,
            latency_ms=record.latency_ms,
            argument_hash=record.argument_hash,
            argument_keys=record.argument_keys,
            result_category=record.result_category,
            error_classification=record.error_classification,
        )
