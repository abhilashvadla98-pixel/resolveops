import logging
from collections.abc import Callable
from time import perf_counter
from typing import TypeVar

from pydantic import BaseModel

from resolveops.agents.budgets import AgentBudgetExceeded, BudgetLedger
from resolveops.agents.models import AgentInvocationRecord, AgentRole, AgentRunStatus
from resolveops.agents.persistence import AgentRunStore, safe_context_hash
from resolveops.agents.prompts import PROMPT_VERSIONS, ROLE_PROMPTS, SCHEMA_VERSIONS
from resolveops.agents.providers import (
    StructuredAgentProvider,
    UsageReportingAgentProvider,
)
from resolveops.observability.metrics import record_agent_run
from resolveops.observability.models import TraceComponent
from resolveops.observability.sinks import DEFAULT_TRACE_SINK, TraceSink
from resolveops.observability.tracing import observed_span
from resolveops.reasoning.errors import ReasoningProviderError

OutputT = TypeVar("OutputT", bound=BaseModel)
LOGGER = logging.getLogger(__name__)


class AgentInvoker:
    def __init__(
        self,
        *,
        provider: StructuredAgentProvider,
        store: AgentRunStore,
        ledger: BudgetLedger,
        observability_sink: TraceSink | None = None,
        on_status: Callable[[AgentInvocationRecord], None] | None = None,
        input_cost_per_million_usd: float | None = None,
        output_cost_per_million_usd: float | None = None,
    ) -> None:
        self.provider = provider
        self.store = store
        self.ledger = ledger
        self.observability_sink = observability_sink or DEFAULT_TRACE_SINK
        self.on_status = on_status
        self.input_cost_per_million_usd = input_cost_per_million_usd
        self.output_cost_per_million_usd = output_cost_per_million_usd

    def invoke(
        self,
        *,
        tenant_id: str,
        workflow_id: str,
        trace_id: str,
        role: AgentRole,
        context: BaseModel | dict[str, object],
        response_model: type[OutputT],
        parent_agent_run_id: str | None = None,
    ) -> tuple[OutputT, str]:
        context_hash = safe_context_hash(context)
        estimated_tokens = _estimated_tokens(context)
        self.ledger.reserve_model_call(estimated_input_tokens=estimated_tokens)
        run = self.store.start(
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            role=role,
            prompt_version=PROMPT_VERSIONS[role],
            schema_version=SCHEMA_VERSIONS[role],
            provider=self.provider.provider_name,
            model=self.provider.model_name,
            context_hash=context_hash,
            trace_id=trace_id,
            parent_agent_run_id=parent_agent_run_id,
        )
        self._notify(run)
        started = perf_counter()
        try:
            with observed_span(
                TraceComponent.LLM,
                f"agent_{role.value}",
                sink=self.observability_sink,
                attributes={
                    "agent_role": role.value,
                    "provider": self.provider.provider_name,
                    "model": self.provider.model_name,
                    "prompt_version": PROMPT_VERSIONS[role],
                },
            ) as span:
                output = self.provider.invoke(
                    instructions=ROLE_PROMPTS[role],
                    context=context,
                    response_model=response_model,
                )
                usage = (
                    self.provider.last_usage
                    if isinstance(self.provider, UsageReportingAgentProvider)
                    else None
                )
                input_tokens = usage.input_tokens if usage else estimated_tokens
                output_tokens = usage.output_tokens if usage else 0
                estimated_cost_usd = self._estimated_cost(input_tokens, output_tokens)
                span.set_attribute("input_tokens", input_tokens)
                span.set_attribute("output_tokens", output_tokens)
                if estimated_cost_usd is not None:
                    span.set_attribute("cost_usd", estimated_cost_usd)
                span.set_attribute("latency_ms", (perf_counter() - started) * 1000)
            self.ledger.record_model_usage(
                actual_input_tokens=input_tokens,
                output_tokens=output_tokens,
                reserved_input_tokens=estimated_tokens,
                estimated_cost_usd=estimated_cost_usd,
            )
            finished = self.store.finish(
                run.agent_run_id,
                output=output,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            self._notify(finished)
            record_agent_run(finished)
            return output, run.agent_run_id
        except AgentBudgetExceeded as exc:
            finished = self.store.finish(
                run.agent_run_id,
                output={"error": exc.code},
                input_tokens=None,
                output_tokens=None,
                status=AgentRunStatus.BUDGET_EXCEEDED,
                error_classification=exc.code,
            )
            self._notify(finished)
            record_agent_run(finished)
            raise
        except ReasoningProviderError as exc:
            finished = self.store.finish(
                run.agent_run_id,
                output={"error": exc.code},
                input_tokens=None,
                output_tokens=None,
                status=AgentRunStatus.FAILED,
                error_classification=exc.code,
            )
            self._notify(finished)
            record_agent_run(finished)
            raise

    def _estimated_cost(self, input_tokens: int, output_tokens: int) -> float | None:
        if self.input_cost_per_million_usd is None or self.output_cost_per_million_usd is None:
            return None
        return (
            input_tokens * self.input_cost_per_million_usd
            + output_tokens * self.output_cost_per_million_usd
        ) / 1_000_000

    def _notify(self, record: AgentInvocationRecord) -> None:
        if self.on_status is None:
            return
        try:
            self.on_status(record)
        except Exception:  # noqa: BLE001 - progress reporting must not alter agent decisions
            LOGGER.warning(
                "agent progress callback failed", extra={"agent_run_id": record.agent_run_id}
            )


def _estimated_tokens(context: BaseModel | dict[str, object]) -> int:
    payload = context.model_dump_json() if isinstance(context, BaseModel) else str(context)
    return max(len(payload) // 4, 1)
