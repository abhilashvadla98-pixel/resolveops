import hashlib
import json
from pathlib import Path

import pytest

from resolveops.evaluation.dataset import (
    EvaluationDatasetError,
    load_workflow_evaluation_cases,
)
from resolveops.evaluation.models import WorkflowObservation
from resolveops.evaluation.scoring import score_workflow_case
from resolveops.evaluation.workflow import evaluate_workflow_cases
from resolveops.workflows.models import WorkflowDecision, WorkflowOutcome

DATASET = Path("evals/workflows/customer_operations.jsonl")


def test_workflow_dataset_is_valid_unique_and_covers_required_failures() -> None:
    cases = load_workflow_evaluation_cases(DATASET)
    dataset_hash = hashlib.sha256(DATASET.read_bytes()).hexdigest()
    evaluation_readme = Path("evals/workflows/README.md").read_text(encoding="utf-8")

    assert len(cases) == 24
    assert dataset_hash in evaluation_readme
    assert len({case.evaluation_id for case in cases}) == len(cases)
    assert {case.category.value for case in cases} == {
        "success",
        "ambiguous",
        "already_refunded",
        "permission",
        "policy",
        "reasoning",
        "tool_failure",
    }
    assert {case.action_behavior.value for case in cases} >= {
        "timeout",
        "disappearing_resource",
        "failed_verification",
    }
    assert {case.reasoning_behavior.value for case in cases} >= {
        "support_refund",
        "manual_review",
        "provider_failure",
        "invalid_reference",
    }


def test_loader_rejects_duplicate_ids_and_reports_line(tmp_path: Path) -> None:
    valid = DATASET.read_text(encoding="utf-8").splitlines()[0]
    duplicate_path = tmp_path / "duplicate.jsonl"
    duplicate_path.write_text(f"{valid}\n{valid}\n", encoding="utf-8")
    invalid_path = tmp_path / "invalid.jsonl"
    invalid_path.write_text('{"evaluation_id":\n', encoding="utf-8")

    with pytest.raises(EvaluationDatasetError, match="duplicate workflow evaluation ID"):
        load_workflow_evaluation_cases(duplicate_path)
    with pytest.raises(EvaluationDatasetError, match=r"invalid workflow evaluation case.*:1"):
        load_workflow_evaluation_cases(invalid_path)


def test_scorer_reports_each_regression_instead_of_hiding_it() -> None:
    evaluation_case = load_workflow_evaluation_cases(DATASET)[1]
    observation = WorkflowObservation(
        outcome=WorkflowOutcome.NEEDS_REVIEW,
        decision=WorkflowDecision.ESCALATE,
        error_code="unexpected_failure",
        new_refund_created=False,
        verified=False,
        node_history=["load_case", "escalate"],
        policy_document_ids=[],
    )

    result = score_workflow_case(evaluation_case, observation)

    assert result.passed is False
    failures = {assertion.name for assertion in result.assertions if not assertion.passed}
    assert failures >= {
        "outcome",
        "decision",
        "error_code",
        "new_refund_created",
        "verified",
        "required_policy",
        "required_node:execute_refund",
    }


def test_customer_operations_workflow_regression_gate() -> None:
    cases = load_workflow_evaluation_cases(DATASET)

    first = evaluate_workflow_cases(cases, dataset_name=DATASET.as_posix())
    second = evaluate_workflow_cases(cases, dataset_name=DATASET.as_posix())

    assert first == second
    assert first.case_count == 24
    assert first.passed_count == 24
    assert first.failed_count == 0
    assert first.pass_rate == 1.0
    assert all(metric.pass_rate == 1.0 for metric in first.category_metrics)
    assert all(result.execution_error is None for result in first.cases)


def test_cli_report_is_machine_readable_shape() -> None:
    cases = load_workflow_evaluation_cases(DATASET)
    report = evaluate_workflow_cases(cases[:1], dataset_name="smoke")

    payload = json.loads(report.model_dump_json())

    assert payload["dataset_name"] == "smoke"
    assert payload["case_count"] == 1
    assert payload["cases"][0]["evaluation_id"] == "WF-EVAL-001"
