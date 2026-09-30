from datetime import UTC, datetime

import pytest

from resolveops.feedback.models import FeedbackKind, FeedbackReviewStatus, OperatorFeedback
from resolveops.feedback.promotion import promote_reviewed_feedback


def _feedback(status: FeedbackReviewStatus) -> OperatorFeedback:
    reviewed = status != FeedbackReviewStatus.PENDING
    return OperatorFeedback(
        feedback_id="FDBK-owner-001",
        case_id="CASE-1001",
        kind=FeedbackKind.CLASSIFICATION_CORRECTION,
        original_value={"issue_type": "duplicate_charge"},
        corrected_value={"issue_type": "authorization_hold"},
        reason="Fresh payment state supports the corrected class.",
        operator_id="OWNER-1",
        review_status=status,
        created_at=datetime(2026, 9, 30, tzinfo=UTC),
        reviewed_by="OWNER-2" if reviewed else None,
        reviewed_at=datetime(2026, 9, 30, 1, tzinfo=UTC) if reviewed else None,
        review_note="Checked against the captured payment state." if reviewed else None,
    )


def test_only_human_reviewed_feedback_can_create_versioned_dataset_candidate(tmp_path) -> None:
    with pytest.raises(ValueError, match="human-reviewed"):
        promote_reviewed_feedback(
            _feedback(FeedbackReviewStatus.PENDING),
            dataset_path=tmp_path / "dataset.jsonl",
            manifest_path=tmp_path / "manifest.json",
            version="1.0.0",
        )

    example, manifest = promote_reviewed_feedback(
        _feedback(FeedbackReviewStatus.REVIEWED),
        dataset_path=tmp_path / "dataset.jsonl",
        manifest_path=tmp_path / "manifest.json",
        version="1.0.0",
    )

    assert example.source_feedback_id == "FDBK-owner-001"
    assert example.expected_value == {"issue_type": "authorization_hold"}
    assert manifest.record_count == 1
    assert len(manifest.sha256) == 64
