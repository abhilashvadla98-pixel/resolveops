import argparse
import json
from pathlib import Path

from resolveops.evaluation.agent_trajectory import (
    evaluate_agent_trajectories,
    load_agent_trajectory_cases,
    save_agent_trajectory_report,
)
from resolveops.evaluation.offline_agents import run_offline_trajectory

DEFAULT_DATASET = Path("evals/agents/trajectories.jsonl")
DEFAULT_OUTPUT = Path("evals/agents/latest-report.json")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic ResolveOps multi-agent trajectory evaluation."
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    cases = load_agent_trajectory_cases(args.dataset)
    report = evaluate_agent_trajectories(
        cases,
        dataset_name=args.dataset.as_posix(),
        runner=run_offline_trajectory,
    )
    save_agent_trajectory_report(report, args.output)
    print(json.dumps(report.model_dump(mode="json"), indent=2))
    return 0 if report.failed_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
