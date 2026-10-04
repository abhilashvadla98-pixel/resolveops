import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from resolveops.agents.budgets import BudgetLedger
from resolveops.agents.invocation import AgentInvoker
from resolveops.agents.models import AgentBudget, AgentRole
from resolveops.agents.persistence import AgentRunStore
from resolveops.agents.prompts import PROMPT_VERSIONS, SCHEMA_VERSIONS
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

    def require_rotated_credential(self) -> str:
        if self.api_key is None:
            raise ValueError("A local Gemini API key is required; it is never written to reports.")
        if not self.key_rotated:
            raise ValueError(
                "Live calls require owner key rotation and RESOLVEOPS_GEMINI_KEY_ROTATED=true."
            )
        return self.api_key.get_secret_value()


def _run_trial(
    case: AgentTrajectoryCase, trial: int, settings: LiveAgentSettings
) -> dict[str, object]:
    api_key = settings.require_rotated_credential()
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
        api_key,
        model=settings.model,
        timeout_seconds=45,
        max_attempts=2,
        max_input_characters=16_000,
        max_output_tokens=1_200,
    )
    runtime = MultiAgentReasoningRuntime(
        invoker=AgentInvoker(
            provider=provider,
            store=store,
            ledger=ledger,
            input_cost_per_million_usd=settings.input_cost_per_million_usd,
            output_cost_per_million_usd=settings.output_cost_per_million_usd,
        ),
        tools=OfflineTrajectoryTools(case, clock=lambda: datetime.now(UTC)),
        run_store=store,
        ledger=ledger,
        context_tool_allowlists={
            AgentRole.INVESTIGATION: [
                "get_case" if case.domain.value == "customer_operations" else "get_it_snapshot"
            ],
            AgentRole.POLICY: ["search_policies"],
            AgentRole.RESOLUTION: [],
            AgentRole.CRITIC: [],
        },
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
        error_detail = None
    except (
        AssertionError,
        ReasoningProviderError,
        ValueError,
        RuntimeError,
        PermissionError,
    ) as exc:
        result = None
        error_code = getattr(exc, "code", type(exc).__name__)
        error_detail = str(exc)[:300]
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
        and result.replan_count == expected.replan_count
        and len(runs) <= expected.max_model_calls
        and len(tools) <= expected.max_tool_calls
    )
    record = {
        "evaluation_id": case.evaluation_id,
        "trial": trial,
        "passed": passed,
        "evaluation_scope": "provider_backed_contract_smoke",
        "business_outcome_evaluated": False,
        "tool_source": "synthetic_contract_fixtures",
        "status": result.status if result else "error",
        "roles": roles,
        "tools": tool_names,
        "citations": citations,
        "critic_decisions": critics,
        "replan_count": result.replan_count if result else None,
        "latency_ms": latency_ms,
        "model_calls": len(runs),
        "tool_calls": len(tools),
        "input_tokens": ledger.usage.input_tokens,
        "output_tokens": ledger.usage.output_tokens,
        "cost_usd": ledger.usage.estimated_cost_usd,
        "error_code": error_code,
        "error_detail": error_detail,
        "per_agent": [
            {
                "role": run.role.value,
                "latency_ms": run.latency_ms,
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "model_calls": 1,
                "tool_calls": run.tool_call_count,
                "output_contract": _output_contract(run.structured_output),
                "cost_usd": (
                    (
                        (run.input_tokens or 0) * settings.input_cost_per_million_usd
                        + (run.output_tokens or 0) * settings.output_cost_per_million_usd
                    )
                    / 1_000_000
                    if run.input_tokens is not None
                    and run.output_tokens is not None
                    and settings.input_cost_per_million_usd is not None
                    and settings.output_cost_per_million_usd is not None
                    else None
                ),
            }
            for run in runs
        ],
    }
    engine.dispose()
    return record


def report_provenance(dataset: Path, settings: LiveAgentSettings) -> dict[str, object]:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = bool(
        subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout.strip()
    )
    return {
        "git_revision": revision,
        "working_tree_dirty": dirty,
        "dataset": str(dataset),
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "provider": "google",
        "model": settings.model,
        "prompt_versions": {role.value: version for role, version in PROMPT_VERSIONS.items()},
        "schema_versions": {role.value: version for role, version in SCHEMA_VERSIONS.items()},
        "environment": "local contract harness; SQLite in-memory telemetry",
        "evaluation_scope": "provider_backed_contract_smoke",
        "business_outcome_evaluated": False,
        "tool_source": "synthetic_contract_fixtures",
    }


def save_new_report(report: dict[str, object], output: Path | None, prefix: str) -> Path:
    path = output or Path("evals/agents/runs") / (
        f"{prefix}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2) + "\n")
    return path


def _output_contract(output: dict[str, object] | None) -> dict[str, object] | None:
    if output is None:
        return None
    facts = output.get("facts")
    evidence_ids = output.get("evidence_ids")
    provenance = output.get("source_provenance")
    missing = output.get("missing_evidence")
    citations = output.get("citations")
    policy_versions = output.get("policy_versions")
    return {
        "complete": output.get("complete"),
        "fact_count": len(facts) if isinstance(facts, list) else None,
        "evidence_id_count": len(evidence_ids) if isinstance(evidence_ids, list) else None,
        "provenance_count": len(provenance) if isinstance(provenance, list) else None,
        "missing_evidence_count": len(missing) if isinstance(missing, list) else None,
        "citation_count": len(citations) if isinstance(citations, list) else None,
        "policy_version_count": (
            len(policy_versions) if isinstance(policy_versions, dict) else None
        ),
        "missing_policy": output.get("missing_policy"),
        "all_facts_fresh": (
            all(isinstance(fact, dict) and fact.get("fresh") is True for fact in facts)
            if isinstance(facts, list) and facts
            else None
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run provider-backed orchestration contract smoke trials with fixture tools."
    )
    parser.add_argument("--dataset", type=Path, default=Path("evals/agents/trajectories.jsonl"))
    parser.add_argument(
        "--output", type=Path, help="New report path; existing files are never replaced"
    )
    parser.add_argument("--tasks", type=int, default=10, choices=range(8, 13))
    parser.add_argument("--trials", type=int, default=3, choices=range(1, 4))
    args = parser.parse_args()
    settings = LiveAgentSettings()
    settings.require_rotated_credential()
    if args.output is not None and args.output.exists():
        raise SystemExit("Refusing to overwrite an existing evaluation report.")
    cases = load_agent_trajectory_cases(args.dataset)[: args.tasks]
    results = [
        _run_trial(case, trial, settings) for case in cases for trial in range(1, args.trials + 1)
    ]
    latencies = sorted(float(item["latency_ms"]) for item in results)
    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "provider": "google",
        "model": settings.model,
        "provenance": report_provenance(args.dataset, settings),
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
            "Contract smoke only: tools return fixture data, not application-store reads.",
            "No approval, refund, settlement, deployed path or business outcome is evaluated.",
            "Expected outcomes are held only in the scorer; this is not a model-quality benchmark.",
            "Synthetic evidence only; no external business system is modified.",
            "Unknown provider pricing remains null rather than being invented.",
            "Quota failures remain visible as failed trials.",
        ],
    }
    output = save_new_report(report, args.output, "provider-contract")
    print(
        json.dumps(
            {"output": str(output), "trials": len(results), "passed": report["passed_trials"]}
        )
    )
    return 0 if report["passed_trials"] == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
