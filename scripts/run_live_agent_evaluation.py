import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from resolveops.agents.budgets import BudgetLedger
from resolveops.agents.invocation import AgentInvoker
from resolveops.agents.models import AgentBudget, AgentRole
from resolveops.agents.persistence import AgentRunStore
from resolveops.agents.providers import GeminiStructuredAgentProvider
from resolveops.agents.runtime import MultiAgentReasoningRuntime
from resolveops.database.base import Base
from resolveops.evaluation.agent_trajectory import AgentTrajectoryCase, load_agent_trajectory_cases
from resolveops.evaluation.offline_agents import OfflineTrajectoryTools
from resolveops.orchestration.graph import HierarchicalAgentOrchestrator
from resolveops.reasoning.errors import ReasoningProviderError


class LiveAgentSettings(BaseSettings):
    api_key: SecretStr | None = None
    key_rotated: bool = False
    model: str = "gemini-3.5-flash-lite"
    input_cost_per_million_usd: float | None = Field(default=None, ge=0)
    output_cost_per_million_usd: float | None = Field(default=None, ge=0)

    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="RESOLVEOPS_GEMINI_", extra="ignore"
    )


def _run_trial(
    case: AgentTrajectoryCase, trial: int, settings: LiveAgentSettings
) -> dict[str, object]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    store = AgentRunStore(factory)
    ledger = BudgetLedger(
        AgentBudget(
            max_agent_steps=20,
            max_model_calls=20,
            max_tool_calls=12,
            max_input_tokens=100_000,
            max_output_tokens=10_000,
        ),
        datetime.now(UTC),
    )
    provider = GeminiStructuredAgentProvider.from_api_key(
        settings.api_key.get_secret_value(),  # type: ignore[union-attr]
        model=settings.model,
        timeout_seconds=45,
        max_attempts=2,
        max_input_characters=16_000,
        max_output_tokens=600,
    )
    runtime = MultiAgentReasoningRuntime(
        invoker=AgentInvoker(
            provider=provider,
            store=store,
            ledger=ledger,
            input_cost_per_million_usd=settings.input_cost_per_million_usd,
            output_cost_per_million_usd=settings.output_cost_per_million_usd,
        ),
        tools=OfflineTrajectoryTools(),
        run_store=store,
        ledger=ledger,
    )
    workflow_id = f"LIVE-{case.evaluation_id}-T{trial}"
    started = perf_counter()
    try:
        result = HierarchicalAgentOrchestrator(runtime).run(
            workflow_id=workflow_id,
            case_id=case.evaluation_id,
            tenant_id="TENANT-LIVE-EVALUATION",
            domain=case.domain,
            objective=case.objective,
            trace_id=f"{case.evaluation_id}-{trial}".encode().hex()[:32].ljust(32, "0"),
        )
        error_code = None
    except (ReasoningProviderError, ValueError, RuntimeError) as exc:
        result = None
        error_code = getattr(exc, "code", type(exc).__name__)
    latency_ms = (perf_counter() - started) * 1_000
    runs = store.list_for_workflow(workflow_id)
    tools = store.list_tool_calls_for_workflow(workflow_id)
    roles = [run.role.value for run in runs]
    tool_names = [tool.tool_name for tool in tools]
    critics = [
        str(run.structured_output.get("decision"))
        for run in runs
        if run.role == AgentRole.CRITIC and run.structured_output
    ]
    citations = sorted(
        {
            str(citation)
            for run in runs
            if run.role == AgentRole.POLICY and run.structured_output
            for citation in run.structured_output.get("citations", [])
        }
    )
    expected = case.expected
    passed = bool(
        result
        and result.status == expected.status
        and {role.value for role in expected.required_roles}.issubset(roles)
        and set(expected.required_tools).issubset(tool_names)
        and not set(expected.forbidden_tools).intersection(tool_names)
        and [decision.value for decision in expected.critic_decisions] == critics
    )
    record = {
        "evaluation_id": case.evaluation_id,
        "trial": trial,
        "passed": passed,
        "status": result.status if result else "error",
        "roles": roles,
        "tools": tool_names,
        "citations": citations,
        "critic_decisions": critics,
        "latency_ms": latency_ms,
        "model_calls": len(runs),
        "tool_calls": len(tools),
        "input_tokens": ledger.usage.input_tokens,
        "output_tokens": ledger.usage.output_tokens,
        "cost_usd": ledger.usage.estimated_cost_usd,
        "error_code": error_code,
        "per_agent": [
            {
                "role": run.role.value,
                "latency_ms": run.latency_ms,
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "model_calls": 1,
                "tool_calls": run.tool_call_count,
                "cost_usd": (
                    (
                        (run.input_tokens or 0) * settings.input_cost_per_million_usd
                        + (run.output_tokens or 0) * settings.output_cost_per_million_usd
                    )
                    / 1_000_000
                    if settings.input_cost_per_million_usd is not None
                    and settings.output_cost_per_million_usd is not None
                    else None
                ),
            }
            for run in runs
        ],
    }
    engine.dispose()
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the live stochastic multi-agent evaluation.")
    parser.add_argument("--dataset", type=Path, default=Path("evals/agents/trajectories.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("evals/agents/live-report.json"))
    parser.add_argument("--tasks", type=int, default=10, choices=range(8, 13))
    parser.add_argument("--trials", type=int, default=3, choices=range(1, 4))
    args = parser.parse_args()
    settings = LiveAgentSettings()
    if settings.api_key is None:
        raise SystemExit("A local Gemini API key is required; it is never written to reports.")
    if not settings.key_rotated:
        raise SystemExit(
            "Live evaluation blocked: rotate the exposed key, then set "
            "RESOLVEOPS_GEMINI_KEY_ROTATED=true locally."
        )
    cases = load_agent_trajectory_cases(args.dataset)[: args.tasks]
    results = [
        _run_trial(case, trial, settings) for case in cases for trial in range(1, args.trials + 1)
    ]
    latencies = sorted(float(item["latency_ms"]) for item in results)
    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "provider": "google",
        "model": settings.model,
        "task_count": len(cases),
        "trials_per_task": args.trials,
        "trial_count": len(results),
        "passed_trials": sum(bool(item["passed"]) for item in results),
        "latency_ms": {
            "p50": latencies[(len(latencies) - 1) // 2],
            "p95": latencies[max(int(len(latencies) * 0.95) - 1, 0)],
        },
        "input_tokens": sum(int(item["input_tokens"]) for item in results),
        "output_tokens": sum(int(item["output_tokens"]) for item in results),
        "model_calls": sum(int(item["model_calls"]) for item in results),
        "tool_calls": sum(int(item["tool_calls"]) for item in results),
        "cost_usd": (
            sum(float(item["cost_usd"]) for item in results)
            if all(item["cost_usd"] is not None for item in results)
            else None
        ),
        "results": results,
        "limitations": [
            "Synthetic evidence only; no external business system is modified.",
            "Unknown provider pricing remains null rather than being invented.",
            "Quota failures remain visible as failed trials.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"trials": len(results), "passed": report["passed_trials"]}))
    return 0 if report["passed_trials"] == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
