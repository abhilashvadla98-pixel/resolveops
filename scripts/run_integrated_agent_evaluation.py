"""Run actual customer workflow outcomes; live inference is explicit and opt-in."""

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import SecretStr, ValidationError
from run_live_agent_evaluation import save_new_report

from resolveops.agents.factory import build_agent_runtime
from resolveops.agents.models import (
    CriticReport,
    InvestigationTurn,
    PolicyTurn,
    ResolutionProposal,
    SupervisorPlan,
)
from resolveops.agents.prompts import PROMPT_VERSIONS, ROLE_PROMPTS, SCHEMA_VERSIONS
from resolveops.config import Settings
from resolveops.evaluation.integrated_agents import (
    TENANT,
    load_integrated_tasks,
    run_integrated_trial,
    summarize_integrated_trials,
)


def source_tree_digest() -> str:
    paths = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "src", "scripts"],
        text=True,
    ).splitlines()
    digest = hashlib.sha256()
    for name in sorted(set(paths)):
        path = Path(name)
        digest.update(name.encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest() if path.is_file() else b"MISSING")
    return digest.hexdigest()


def contract_digests() -> dict[str, object]:
    return {
        "source_tree_sha256": source_tree_digest(),
        "tracked_diff_sha256": hashlib.sha256(
            subprocess.check_output(["git", "diff", "HEAD", "--", "src", "scripts"])
        ).hexdigest(),
        "prompt_sha256": {
            role.value: hashlib.sha256(text.encode()).hexdigest()
            for role, text in ROLE_PROMPTS.items()
        },
        "schema_sha256": {
            model.__name__: hashlib.sha256(
                json.dumps(model.model_json_schema(), sort_keys=True).encode()
            ).hexdigest()
            for model in (
                SupervisorPlan,
                InvestigationTurn,
                PolicyTurn,
                ResolutionProposal,
                CriticReport,
            )
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("evals/integrated/cases.jsonl"))
    parser.add_argument(
        "--policy-directory", type=Path, default=Path("domain_packs/customer_operations/policies")
    )
    parser.add_argument("--mode", choices=["rules_only", "live_multi_role"], default="rules_only")
    parser.add_argument("--tasks", type=int, choices=range(1, 11), default=10)
    parser.add_argument("--trials", type=int, choices=range(1, 4), default=1)
    parser.add_argument("--output", type=Path, help="New immutable report path")
    args = parser.parse_args()
    output = args.output or Path("artifacts/integrated-evaluation") / (
        f"{args.mode}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}.json"
    )
    if output.exists():
        raise SystemExit("Refusing to overwrite an existing evaluation report.")
    tasks = load_integrated_tasks(args.dataset)[: args.tasks]
    settings = None
    if args.mode == "live_multi_role":
        try:
            settings = Settings(
                database_url=SecretStr("sqlite:///:memory:"),
            )
        except ValidationError:
            raise SystemExit(
                "Invalid local evaluation settings; check configuration without sharing secret values."
            ) from None
        if settings.gemini_api_key is None or not settings.gemini_key_rotated:
            raise SystemExit(
                "Live calls require a local rotated Gemini key and owner rotation acknowledgement."
            )
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], text=True).strip())
    digests = contract_digests()
    records = []
    stopped_reason = None
    for task in tasks:
        for trial in range(1, args.trials + 1):
            # Only the runtime and case tools reach the provider. The task/expectations do not.
            builder = (
                (lambda factory: build_agent_runtime(factory, settings, tenant_id=TENANT))
                if settings
                else None
            )
            record = run_integrated_trial(
                task,
                trial,
                policy_directory=args.policy_directory,
                runtime_builder=builder,
                execution_mode=args.mode,
            )
            records.append(record)
            print(
                json.dumps(
                    {
                        "evaluation_id": task.evaluation_id,
                        "trial": trial,
                        "passed": record["passed"],
                        "error": record["error"],
                    }
                ),
                flush=True,
            )
            if "agent_provider_rate_limited" in record["provider_failures"]:
                stopped_reason = "Provider quota/rate limit; no further tasks attempted."
                break
        if stopped_reason:
            break
    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "evaluation_scope": "normal_customer_workflow_business_outcome",
        "code_revision": revision,
        "working_tree_dirty": dirty,
        "content_identity": digests,
        "source_changed_during_run": source_tree_digest() != digests["source_tree_sha256"],
        "dataset": str(args.dataset),
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "prompt_versions": {role.value: version for role, version in PROMPT_VERSIONS.items()},
        "schema_versions": {role.value: version for role, version in SCHEMA_VERSIONS.items()},
        "mode": args.mode,
        "provider": "google" if settings else None,
        "model": settings.gemini_model if settings else None,
        "per_call_output_token_limit": settings.agent_max_output_tokens if settings else None,
        "task_count": len(tasks),
        "trials_per_task": args.trials,
        "attempted_trials": len(records),
        "requested_trials": len(tasks) * args.trials,
        "not_attempted_trials": len(tasks) * args.trials - len(records),
        "stopped_reason": stopped_reason,
        **summarize_integrated_trials(records),
        "results": records,
        "limitations": [
            "Synthetic isolated source records; payment events and approvals are simulated.",
            "Uses application services directly, not HTTP authentication or deployed infrastructure.",
            "Sequential advisory roles with deterministic early safety stops, not arbitrary adaptive supervisor routing; single-agent comparison is unproven.",
            "No human labels, commercial adoption or production-scale claim follows from this run.",
            "Rules-only repeated trials are regression checks, not stochastic model evidence.",
        ],
    }
    save_new_report(report, output, "integrated")
    print(
        json.dumps(
            {"output": str(output), "correct": report["correct_trials"], "attempted": len(records)}
        )
    )
    return 0 if all(record["passed"] for record in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
