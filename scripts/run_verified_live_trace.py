import json
from datetime import UTC, datetime
from pathlib import Path

from run_live_agent_evaluation import LiveAgentSettings, _run_trial

from resolveops.evaluation.agent_trajectory import load_agent_trajectory_cases


def main() -> int:
    case = load_agent_trajectory_cases(Path("evals/agents/trajectories.jsonl"))[0]
    result = _run_trial(case, 1, LiveAgentSettings())
    artifact = {
        "measured_at": datetime.now(UTC).isoformat(),
        "provider_backed": True,
        "synthetic_data_only": True,
        "credential_stored": False,
        "result": result,
        "limitations": [
            "This is one verified trace, not a general model-quality claim.",
            "No external business system was modified.",
            "Cost remains null when provider pricing is not configured.",
        ],
    }
    output = Path("evals/agents/verified-live-trace.json")
    output.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(output),
                "passed": result["passed"],
                "roles": result["roles"],
                "tools": result["tools"],
            }
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
