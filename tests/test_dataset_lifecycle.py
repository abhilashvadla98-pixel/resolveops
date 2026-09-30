import json
from csv import DictReader, DictWriter
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from resolveops.database.base import Base
from resolveops.database.seed import seed_customer_operations
from resolveops.evaluation.dataset_manifest import load_manifest_catalog
from resolveops.evaluation.experiments import (
    ExperimentMetrics,
    compare_experiments,
    create_experiment_run,
    load_experiment,
    save_experiment,
)
from resolveops.evaluation.human_review import export_review_sheet, import_completed_reviews
from resolveops.feedback.models import FeedbackKind, FeedbackReviewStatus
from resolveops.feedback.store import OperatorFeedbackStore

ROOT = Path(__file__).parents[1]


def test_all_evaluation_manifests_match_versioned_datasets() -> None:
    catalog = load_manifest_catalog(ROOT / "evals" / "manifests", repository_root=ROOT)

    assert len(catalog) == 7
    assert sum(item.record_count for item in catalog.values()) == 154


def test_experiment_artifact_records_reproducibility_metadata(tmp_path: Path) -> None:
    catalog = load_manifest_catalog(ROOT / "evals" / "manifests", repository_root=ROOT)
    dataset = catalog["resolveops.retrieval.customer_operations@1.0.0"]
    metrics = ExperimentMetrics(
        task={"recall_at_3": 0.98, "mrr": 0.9467},
        latency_ms={"p50": 3.641, "p95": 5.079},
        failure_counts={"retrieval_wrong_policy": 1},
    )
    first = create_experiment_run(
        repository_root=ROOT,
        dataset=dataset,
        provider="offline",
        model="deterministic-baseline",
        prompt_version="none",
        schema_version="retrieval-v1",
        embedding_model="BAAI/bge-small-en-v1.5",
        retrieval_configuration={"method": "bm25", "k": 3},
        policy_index_version="customer-policies-2026-09-29",
        metrics=metrics,
        experiment_id="EXP-TEST-BM25",
    )
    second = first.model_copy(
        update={
            "experiment_id": "EXP-TEST-HYBRID",
            "retrieval_configuration": {"method": "hybrid", "k": 3},
        }
    )
    target = tmp_path / "experiment.json"
    save_experiment(first, target)

    assert load_experiment(target) == first
    comparison = compare_experiments([first, second])
    assert comparison[0]["retrieval"]["method"] == "bm25"
    assert comparison[1]["retrieval"]["method"] == "hybrid"


def test_feedback_stays_pending_until_explicit_human_review() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_customer_operations(session)
        store = OperatorFeedbackStore(session)
        feedback = store.create(
            case_id="CASE-1001",
            workflow_id=None,
            trace_id="TRACE-1",
            kind=FeedbackKind.CLASSIFICATION_CORRECTION,
            original_value={"issue_type": "duplicate_charge"},
            corrected_value={"issue_type": "authorization_hold"},
            reason="The second payment was authorized but never captured.",
            operator_id="OPERATOR-1",
            model_provider="offline",
            model_name="scripted",
            prompt_version="intake-v1",
        )
        session.commit()
        assert feedback.review_status == FeedbackReviewStatus.PENDING
        reviewed = store.review(
            feedback.feedback_id,
            status=FeedbackReviewStatus.REVIEWED,
            reviewer_id="REVIEWER-1",
            note="Correction is supported by payment state.",
        )
        session.commit()

    assert reviewed is not None
    assert reviewed.review_status == FeedbackReviewStatus.REVIEWED
    assert reviewed.dataset_example_id is None


def test_response_review_export_is_unlabelled_and_import_requires_owner_labels(
    tmp_path: Path,
) -> None:
    dataset = ROOT / "evals" / "responses" / "customer_responses.jsonl"
    review = tmp_path / "review.csv"
    assert export_review_sheet(dataset, review) == 24
    with review.open(encoding="utf-8-sig") as stream:
        rows = list(DictReader(stream))
    assert len(rows) == 24
    assert all(not row["decision"] and not row["reviewer"] for row in rows)

    rows[0]["decision"] = "approved"
    rows[0]["reviewer"] = "Project owner"
    rows[0]["review_note"] = "Grounded and appropriately cautious."
    broken = tmp_path / "broken.csv"
    headers = list(rows[0])
    with broken.open("w", newline="", encoding="utf-8") as stream:
        writer = DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerow(rows[0])
    with pytest.raises(ValueError, match="missing yes/no rubric fields"):
        import_completed_reviews(dataset, broken, tmp_path / "candidate.jsonl")


def test_response_dataset_truth_remains_zero_human_labels() -> None:
    path = ROOT / "evals" / "responses" / "customer_responses.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert all(
        row.get("human_review_status", "pending_human_review") == "pending_human_review"
        for row in rows
    )
