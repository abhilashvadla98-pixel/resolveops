import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from resolveops.evaluation.agent_trajectory import load_agent_trajectory_cases
from resolveops.evaluation.offline_agents import run_offline_trajectory


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare reviewed-memory context with no memory on deterministic trajectories."
    )
    parser.add_argument("--dataset", type=Path, default=Path("evals/agents/trajectories.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("evals/agents/memory-ablation.json"))
    parser.add_argument("--cases", type=int, default=8)
    args = parser.parse_args()
    cases = [
        case
        for case in load_agent_trajectory_cases(args.dataset)
        if case.domain.value == "customer_operations"
    ][: args.cases]
    results = []
    for case in cases:
        without = run_offline_trajectory(case, memory_enabled=False)
        with_memory = run_offline_trajectory(case, memory_enabled=True)
        results.append(
            {
                "evaluation_id": case.evaluation_id,
                "without_memory": without.model_dump(mode="json"),
                "with_reviewed_memory": with_memory.model_dump(mode="json"),
                "outcome_equal": without.status == with_memory.status,
                "routing_equal": sorted(without.roles) == sorted(with_memory.roles),
                "token_delta": (with_memory.input_tokens + with_memory.output_tokens)
                - (without.input_tokens + without.output_tokens),
            }
        )
    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "mode": "deterministic_offline_ablation",
        "case_count": len(results),
        "results": results,
        "limitations": [
            "This isolates reviewed-memory context plumbing with a deterministic provider double.",
            "It does not claim that memory improves live-model answer quality.",
            "Only human-reviewed, tenant-scoped, policy-version-matched memory is eligible.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(results), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
