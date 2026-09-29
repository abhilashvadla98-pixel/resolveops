import json
from pathlib import Path

import pytest

from resolveops.evaluation.response_evaluation import (
    ResponseDatasetError,
    evaluate_customer_responses,
    load_response_evaluation_cases,
)

DATASET = Path("evals/responses/customer_responses.jsonl")


def test_response_dataset_has_24_honestly_unreviewed_candidates() -> None:
    cases = load_response_evaluation_cases(DATASET)
    report = evaluate_customer_responses(cases)

    assert report.candidate_count == 24
    assert report.automated_passed_count == 24
    assert report.automated_failed_count == 0
    assert report.human_reviewed_count == 0
    assert report.human_approved_count == 0
    assert report.pending_human_review_count == 24
    assert {result.outcome.value for result in report.cases} == {
        "action_verified",
        "waiting_external",
        "needs_review",
    }
    assert all(result.automated_passed for result in report.cases)


def test_response_dataset_rejects_duplicate_ids(tmp_path: Path) -> None:
    line = DATASET.read_text(encoding="utf-8").splitlines()[0]
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(f"{line}\n{line}\n", encoding="utf-8")

    with pytest.raises(ResponseDatasetError, match="duplicate response evaluation ID"):
        load_response_evaluation_cases(duplicate)


def test_completed_human_review_requires_identity_and_note(tmp_path: Path) -> None:
    payload = json.loads(DATASET.read_text(encoding="utf-8").splitlines()[0])
    payload["human_review_status"] = "approved"
    invalid = tmp_path / "invalid-review.jsonl"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ResponseDatasetError, match="invalid response evaluation case"):
        load_response_evaluation_cases(invalid)
