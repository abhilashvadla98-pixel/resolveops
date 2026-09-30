from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from resolveops.agents.budgets import AgentBudgetExceeded, BudgetLedger
from resolveops.agents.context import AgentContextBuilder
from resolveops.agents.invocation import AgentInvoker
from resolveops.agents.models import (
    AgentBudget,
    AgentDomain,
    AgentInvocationRecord,
    MultiAgentReasoningResult,
)
from resolveops.agents.persistence import AgentRunStore
from resolveops.agents.providers import GeminiStructuredAgentProvider
from resolveops.agents.runtime import MultiAgentReasoningRuntime
from resolveops.agents.tools import AgentReadToolRegistry
from resolveops.api.dependencies import get_principal, get_tenant_session
from resolveops.config import get_settings
from resolveops.database.session import create_session_factory
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.models.common import DomainModel, Identifier, NonEmptyText
from resolveops.operations.auth import has_permission
from resolveops.operations.models import Permission
from resolveops.orchestration.graph import HierarchicalAgentOrchestrator
from resolveops.reasoning.errors import ReasoningProviderError
from resolveops.security.models import SecurityPrincipal

router = APIRouter(prefix="/api/v1/agent-workflows", tags=["multi-agent"])
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
    provider = GeminiStructuredAgentProvider.from_api_key(
        settings.gemini_api_key.get_secret_value(),
        model=settings.gemini_model,
        timeout_seconds=settings.gemini_timeout_seconds,
        max_attempts=settings.gemini_max_attempts,
        max_input_characters=min(settings.gemini_max_input_characters, 16_000),
        max_output_tokens=min(settings.gemini_max_output_tokens, 600),
    )
    store = AgentRunStore(factory)
    ledger = BudgetLedger(AgentBudget(), datetime.now(UTC))
    runtime = MultiAgentReasoningRuntime(
        invoker=AgentInvoker(provider=provider, store=store, ledger=ledger),
        tools=AgentReadToolRegistry(factory, FeatureHashEmbeddingProvider(dimensions=128)),
        run_store=store,
        ledger=ledger,
        context_builder=AgentContextBuilder(max_characters=16_000),
    )
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


@router.get("/{workflow_id}/runs", response_model=list[AgentInvocationRecord])
def list_agent_runs(
    workflow_id: str,
    session: DatabaseSession,
    principal: Principal,
) -> list[AgentInvocationRecord]:
    _require_access(principal)
    records = AgentRunStore(_factory(session)).list_for_workflow(workflow_id)
    return [item for item in records if item.tenant_id == principal.tenant_id]
