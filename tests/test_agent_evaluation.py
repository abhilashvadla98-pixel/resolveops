from pathlib import Path

from resolveops.evaluation.agent_trajectory import (
    evaluate_agent_trajectories,
    load_agent_trajectory_cases,
)
from resolveops.evaluation.dataset_manifest import verify_dataset_manifest
from resolveops.evaluation.offline_agents import run_offline_trajectory

DATASET = Path("evals/agents/trajectories.jsonl")
MANIFEST = Path("evals/manifests/agent-trajectories-v1.json")


def test_agent_trajectory_manifest_and_dataset_are_versioned() -> None:
    manifest = verify_dataset_manifest(MANIFEST, repository_root=Path.cwd())
    cases = load_agent_trajectory_cases(DATASET)

    assert manifest.record_count == 22
    assert len(cases) == 22
    assert {case.domain.value for case in cases} == {"customer_operations", "employee_it"}
    assert {case.scenario for case in cases} == {"accept", "revise_once", "escalate"}


def test_offline_agent_trajectory_suite_passes_real_orchestrator_contracts() -> None:
    report = evaluate_agent_trajectories(
        load_agent_trajectory_cases(DATASET),
        dataset_name=DATASET.as_posix(),
        runner=run_offline_trajectory,
    )

    assert report.case_count == 22
    assert report.passed_count == 22
    assert report.failed_count == 0
    assert report.model_calls > report.case_count
    assert report.tool_calls > 0
    assert report.output_tokens == 0
    assert all(
        not set(result.observation.tools).intersection(
            {"create_refund", "send_notification", "grant_access", "approve_request"}
        )
        for result in report.results
    )
