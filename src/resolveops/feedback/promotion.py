import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from resolveops.feedback.models import FeedbackReviewStatus, OperatorFeedback
from resolveops.models.common import DomainModel, Identifier, NonEmptyText


class FeedbackDatasetExample(DomainModel):
    example_id: Identifier
    source_feedback_id: Identifier
    case_id: Identifier
    kind: Identifier
    original_value: dict[str, object]
    expected_value: dict[str, object]
    correction_reason: NonEmptyText
    reviewer: Identifier
    review_note: NonEmptyText


class FeedbackDatasetManifest(DomainModel):
    dataset_id: Identifier
    version: NonEmptyText
    record_count: int = Field(ge=1)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    generated_at: datetime
    source: str = "owner-reviewed operator corrections only"


def promote_reviewed_feedback(
    feedback: OperatorFeedback,
    *,
    dataset_path: Path,
    manifest_path: Path,
    version: str,
) -> tuple[FeedbackDatasetExample, FeedbackDatasetManifest]:
    """Create a versioned candidate dataset record; callers commit DB state separately."""
    if feedback.review_status != FeedbackReviewStatus.REVIEWED:
        raise ValueError("feedback must be human-reviewed before dataset promotion")
    if feedback.reviewed_by is None or not feedback.review_note:
        raise ValueError("feedback promotion requires reviewer identity and note")
    example = FeedbackDatasetExample(
        example_id=f"FDBK-EX-{feedback.feedback_id.removeprefix('FDBK-')}",
        source_feedback_id=feedback.feedback_id,
        case_id=feedback.case_id,
        kind=feedback.kind.value,
        original_value=feedback.original_value,
        expected_value=feedback.corrected_value,
        correction_reason=feedback.reason,
        reviewer=feedback.reviewed_by,
        review_note=feedback.review_note,
    )
    existing = _load_examples(dataset_path)
    if any(item.source_feedback_id == feedback.feedback_id for item in existing):
        raise ValueError("feedback has already been added to this dataset")
    examples = sorted([*existing, example], key=lambda item: item.example_id)
    payload = "".join(item.model_dump_json() + "\n" for item in examples)
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_text(payload, encoding="utf-8")
    manifest = FeedbackDatasetManifest(
        dataset_id="resolveops.feedback.owner_corrections",
        version=version,
        record_count=len(examples),
        sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        generated_at=datetime.now(UTC),
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return example, manifest


def _load_examples(path: Path) -> list[FeedbackDatasetExample]:
    if not path.exists():
        return []
    return [
        FeedbackDatasetExample.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
