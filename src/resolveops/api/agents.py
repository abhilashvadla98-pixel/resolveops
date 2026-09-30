import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from resolveops.agents.budgets import AgentBudgetExceeded
from resolveops.agents.factory import build_agent_runtime
from resolveops.agents.models import (
    AgentDomain,
    AgentInvocationRecord,
    MultiAgentReasoningResult,
)
from resolveops.agents.persistence import AgentRunStore
from resolveops.api.dependencies import get_principal, get_tenant_session
from resolveops.config import get_settings
from resolveops.database.session import create_session_factory
from resolveops.jobs.coordination import build_wakeup_channel
from resolveops.jobs.models import (
    TERMINAL_JOB_STATUSES,
    AgentWorkflowJob,
    EnqueueAgentWorkflowRequest,
    QueueHealth,
)
from resolveops.jobs.store import AgentJobStore, QueueCapacityExceeded
from resolveops.models.common import DomainModel, Identifier, NonEmptyText
from resolveops.observability.metrics import record_agent_queue_health
from resolveops.operations.auth import has_permission
from resolveops.operations.models import Permission
from resolveops.orchestration.graph import HierarchicalAgentOrchestrator
from resolveops.reasoning.errors import ReasoningProviderError
from resolveops.security.models import SecurityPrincipal

router = APIRouter(prefix="/api/v1/agent-workflows", tags=["multi-agent"])
LOGGER = logging.getLogger(__name__)
DatabaseSession = Annotated[Session, Depends(get_tenant_session)]
Principal = Annotated[SecurityPrincipal, Depends(get_principal)]


class AgentWorkflowRequest(DomainModel):
    workflow_id: Identifier
    case_id: Identifier
    domain: AgentDomain
    objective: NonEmptyText


def _factory(session: Session) -> sessionmaker[Session]:
    engine = session.get_bind()
    if not isinstance(engine, Engine):
        raise TypeError("agent workflow API requires an engine-backed session")
    return create_session_factory(engine)


def _require_access(principal: SecurityPrincipal) -> None:
    if not has_permission(principal.actor(), Permission.READ_OPERATIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="permission denied")


@router.post("", response_model=MultiAgentReasoningResult)
def run_agent_workflow(
    body: AgentWorkflowRequest,
    session: DatabaseSession,
    principal: Principal,
) -> MultiAgentReasoningResult:
    _require_access(principal)
    settings = get_settings()
    if settings.gemini_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="multi-agent reasoning is not configured",
        )
    factory = _factory(session)
    runtime = build_agent_runtime(factory, settings, tenant_id=principal.tenant_id)
    try:
        return HierarchicalAgentOrchestrator(runtime).run(
            workflow_id=body.workflow_id,
            case_id=body.case_id,
            tenant_id=principal.tenant_id,
            domain=body.domain,
            objective=body.objective,
            trace_id=uuid4().hex,
        )
    except AgentBudgetExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"multi-agent workflow stopped safely: {exc.code}",
        ) from exc
    except ReasoningProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"multi-agent provider failed safely: {exc.code}",
        ) from exc


@router.post("/jobs", response_model=AgentWorkflowJob, status_code=status.HTTP_202_ACCEPTED)
def enqueue_agent_workflow(
    body: EnqueueAgentWorkflowRequest,
    session: DatabaseSession,
    principal: Principal,
) -> AgentWorkflowJob:
    _require_access(principal)
    settings = get_settings()
    if not settings.agent_queue_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="background agent queue is not enabled",
        )
    if settings.gemini_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="multi-agent reasoning is not configured",
        )
    store = AgentJobStore(
        _factory(session),
        capacity=settings.agent_queue_capacity,
        lease_seconds=settings.agent_job_lease_seconds,
    )
    try:
        job = store.enqueue(
            tenant_id=principal.tenant_id,
            workflow_id=body.workflow_id,
            case_id=body.case_id,
            domain=body.domain,
            objective=body.objective,
            idempotency_key=body.idempotency_key,
            max_attempts=settings.agent_job_max_attempts,
        )
    except QueueCapacityExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="background agent queue is temporarily full",
            headers={"Retry-After": str(settings.agent_worker_poll_seconds)},
        ) from exc
    try:
        build_wakeup_channel(settings.redis_url).notify()
    except Exception:  # noqa: BLE001 - Redis errors vary by installed client version
        # The durable PostgreSQL job remains available for polling workers.
        LOGGER.warning("queue wake-up failed; polling worker will claim durable job")
    return job


@router.get("/jobs/health", response_model=QueueHealth)
def agent_queue_health(
    session: DatabaseSession,
    principal: Principal,
) -> QueueHealth:
    _require_access(principal)
    settings = get_settings()
    health = AgentJobStore(_factory(session), capacity=settings.agent_queue_capacity).health()
    record_agent_queue_health(
        pending=health.pending,
        running=health.running,
        retrying=health.retrying,
        dead_letter=health.dead_letter,
    )
    return health


@router.get("/jobs/{job_id}", response_model=AgentWorkflowJob)
def get_agent_job(
    job_id: str,
    session: DatabaseSession,
    principal: Principal,
) -> AgentWorkflowJob:
    _require_access(principal)
    job = AgentJobStore(_factory(session)).get(job_id, principal.tenant_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent job not found")
    return job


@router.get("/jobs/{job_id}/events", response_model=None)
async def stream_agent_job_events(
    job_id: str,
    request: Request,
    session: DatabaseSession,
    principal: Principal,
) -> StreamingResponse:
    _require_access(principal)
    store = AgentJobStore(_factory(session))
    if store.get(job_id, principal.tenant_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent job not found")
    try:
        last_event_id = max(int(request.headers.get("last-event-id", "0") or "0"), 0)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid Last-Event-ID"
        ) from exc

    async def event_stream() -> AsyncIterator[str]:
        cursor = last_event_id
        idle_ticks = 0
        while not await request.is_disconnected():
            events = store.events_after(job_id, principal.tenant_id, cursor)
            for event in events:
                cursor = event.event_id
                payload = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
                yield f"id: {cursor}\nevent: {event.event_type.value}\ndata: {payload}\n\n"
                if event.status in TERMINAL_JOB_STATUSES:
                    return
            idle_ticks += 1
            if idle_ticks % 15 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{workflow_id}/runs", response_model=list[AgentInvocationRecord])
def list_agent_runs(
    workflow_id: str,
    session: DatabaseSession,
    principal: Principal,
) -> list[AgentInvocationRecord]:
    _require_access(principal)
    records = AgentRunStore(_factory(session)).list_for_workflow(workflow_id)
    return [item for item in records if item.tenant_id == principal.tenant_id]
