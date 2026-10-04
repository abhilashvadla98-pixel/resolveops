import json
from datetime import UTC, datetime
from pathlib import Path

from run_live_agent_evaluation import (
    LiveAgentSettings,
    _run_trial,
    report_provenance,
    save_new_report,
)

from resolveops.evaluation.agent_trajectory import load_agent_trajectory_cases


def main() -> int:
    dataset = Path("evals/agents/trajectories.jsonl")
    case = load_agent_trajectory_cases(dataset)[0]
    settings = LiveAgentSettings()
    result = _run_trial(case, 1, settings)
    artifact = {
        "measured_at": datetime.now(UTC).isoformat(),
        "provider_backed": True,
        "synthetic_data_only": True,
        "credential_stored": False,
        "provenance": report_provenance(dataset, settings),
        "result": result,
        "limitations": [
            "Provider-backed contract smoke with fixture tools, not a normal-workflow trace.",
            "No approval, refund, settlement or deployed path is exercised.",
            "No external business system was modified.",
            "Cost remains null when provider pricing is not configured.",
        ],
    }
    output = save_new_report(artifact, None, "provider-contract-trace")
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
