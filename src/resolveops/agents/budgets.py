from dataclasses import dataclass, field
from datetime import UTC, datetime

from resolveops.agents.models import AgentBudget, AgentBudgetUsage


class AgentBudgetExceeded(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class BudgetLedger:
    budget: AgentBudget
    started_at: datetime
    usage: AgentBudgetUsage = field(default_factory=AgentBudgetUsage)
    cost_coverage_complete: bool = True

    def reserve_model_call(self, *, estimated_input_tokens: int = 0) -> None:
        next_usage = self.usage.model_copy(
            update={
                "agent_steps": self.usage.agent_steps + 1,
                "model_calls": self.usage.model_calls + 1,
                "input_tokens": self.usage.input_tokens + estimated_input_tokens,
            }
        )
        self._validate(next_usage)
        self.usage = next_usage

    def record_model_usage(
        self,
        *,
        actual_input_tokens: int,
        output_tokens: int,
        reserved_input_tokens: int = 0,
        estimated_cost_usd: float | None = None,
    ) -> None:
        if estimated_cost_usd is None:
            self.cost_coverage_complete = False
        next_usage = self.usage.model_copy(
            update={
                "input_tokens": (
                    self.usage.input_tokens - reserved_input_tokens + actual_input_tokens
                ),
                "output_tokens": self.usage.output_tokens + output_tokens,
                "estimated_cost_usd": (
                    None
                    if not self.cost_coverage_complete
                    else (self.usage.estimated_cost_usd or 0) + (estimated_cost_usd or 0)
                ),
            }
        )
        self.usage = next_usage
        self._validate(next_usage)

    def consume_tool_call(self) -> None:
        next_usage = self.usage.model_copy(update={"tool_calls": self.usage.tool_calls + 1})
        self._validate(next_usage)
        self.usage = next_usage

    def check_time(self, now: datetime | None = None) -> None:
        elapsed = ((now or datetime.now(UTC)) - self.started_at).total_seconds()
        if elapsed > self.budget.max_wall_clock_seconds:
            raise AgentBudgetExceeded("wall_clock_budget_exceeded")

    def _validate(self, usage: AgentBudgetUsage) -> None:
        if usage.agent_steps > self.budget.max_agent_steps:
            raise AgentBudgetExceeded("agent_step_budget_exceeded")
        if usage.model_calls > self.budget.max_model_calls:
            raise AgentBudgetExceeded("model_call_budget_exceeded")
        if usage.tool_calls > self.budget.max_tool_calls:
            raise AgentBudgetExceeded("tool_call_budget_exceeded")
        if usage.input_tokens > self.budget.max_input_tokens:
            raise AgentBudgetExceeded("input_token_budget_exceeded")
        if usage.output_tokens > self.budget.max_output_tokens:
            raise AgentBudgetExceeded("output_token_budget_exceeded")
        if (
            self.budget.optional_cost_limit_usd is not None
            and usage.estimated_cost_usd is not None
            and usage.estimated_cost_usd > self.budget.optional_cost_limit_usd
        ):
            raise AgentBudgetExceeded("cost_budget_exceeded")
        self.check_time()
