from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from resolveops.agents.budgets import BudgetLedger
from resolveops.agents.context import AgentContextBuilder
from resolveops.agents.invocation import AgentInvoker
from resolveops.agents.models import AgentBudget, AgentInvocationRecord
from resolveops.agents.persistence import AgentRunStore
from resolveops.agents.providers import GeminiStructuredAgentProvider
from resolveops.agents.runtime import MultiAgentReasoningRuntime
from resolveops.agents.tools import AgentReadToolRegistry
from resolveops.config import Settings
from resolveops.interfaces.mcp_client import MCPReadClient
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.memory.store import ReviewedResolutionMemoryStore


def build_agent_runtime(
    session_factory: sessionmaker[Session],
    settings: Settings,
    *,
    tenant_id: str,
    on_status: Callable[[AgentInvocationRecord], None] | None = None,
) -> MultiAgentReasoningRuntime:
    if settings.gemini_api_key is None:
        raise ValueError("multi-agent reasoning is not configured")
    if not settings.gemini_key_rotated:
        raise ValueError("live agent runtime requires owner acknowledgement of key rotation")
    provider = GeminiStructuredAgentProvider.from_api_key(
        settings.gemini_api_key.get_secret_value(),
        model=settings.gemini_model,
        timeout_seconds=settings.gemini_timeout_seconds,
        max_attempts=settings.gemini_max_attempts,
        max_input_characters=min(settings.gemini_max_input_characters, 16_000),
        max_output_tokens=settings.agent_max_output_tokens,
    )
    store = AgentRunStore(session_factory)
    ledger = BudgetLedger(
        AgentBudget(
            max_agent_steps=16,
            max_model_calls=16,
            max_input_tokens=48_000,
            max_output_tokens=8_000,
            optional_cost_limit_usd=settings.agent_cost_limit_usd,
        ),
        datetime.now(UTC),
    )
    return MultiAgentReasoningRuntime(
        invoker=AgentInvoker(
            provider=provider,
            store=store,
            ledger=ledger,
            on_status=on_status,
            input_cost_per_million_usd=settings.agent_input_cost_per_million_usd,
            output_cost_per_million_usd=settings.agent_output_cost_per_million_usd,
        ),
        tools=AgentReadToolRegistry(
            session_factory,
            FeatureHashEmbeddingProvider(dimensions=128),
            tenant_id=tenant_id,
            external_read_client=(
                MCPReadClient(
                    settings.agent_mcp_server_url,
                    tenant_id=tenant_id,
                    timeout_seconds=settings.agent_mcp_timeout_seconds,
                )
                if settings.agent_mcp_server_url is not None
                else None
            ),
        ),
        run_store=store,
        ledger=ledger,
        context_builder=AgentContextBuilder(max_characters=16_000),
        max_investigation_turns=8,
        memory_retriever=(
            ReviewedResolutionMemoryStore(session_factory)
            if settings.agent_reviewed_memory_enabled
            else None
        ),
    )
