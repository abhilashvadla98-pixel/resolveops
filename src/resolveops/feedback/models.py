from enum import Enum

from pydantic import Field, model_validator

from resolveops.models.common import AwareDatetime, DomainModel, Identifier, NonEmptyText


class FeedbackKind(str, Enum):
    CLASSIFICATION_CORRECTION = "classification_correction"
    RECOMMENDATION_REJECTED = "recommendation_rejected"
    APPROVAL_REJECTED = "approval_rejected"
    RESOLUTION_CHANGED = "resolution_changed"
    CUSTOMER_RESPONSE_EDITED = "customer_response_edited"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"


class FeedbackReviewStatus(str, Enum):
    PENDING = "pending"
    REVIEWED = "reviewed"
    REJECTED = "rejected"
    PROMOTED = "promoted"


class OperatorFeedback(DomainModel):
    feedback_id: Identifier
    case_id: Identifier
    workflow_id: Identifier | None = None
    trace_id: Identifier | None = None
    kind: FeedbackKind
    original_value: dict[str, object]
    corrected_value: dict[str, object]
    reason: NonEmptyText
    operator_id: Identifier
    model_provider: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    review_status: FeedbackReviewStatus = FeedbackReviewStatus.PENDING
    created_at: AwareDatetime
    reviewed_by: Identifier | None = None
    reviewed_at: AwareDatetime | None = None
    review_note: str | None = Field(default=None, max_length=2000)
    dataset_example_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_review(self) -> "OperatorFeedback":
        if self.review_status == FeedbackReviewStatus.PENDING:
            if self.reviewed_by is not None or self.reviewed_at is not None:
                raise ValueError("pending feedback cannot contain reviewer fields")
        elif self.reviewed_by is None or self.reviewed_at is None:
            raise ValueError("reviewed feedback requires reviewer and timestamp")
        if self.review_status == FeedbackReviewStatus.PROMOTED and self.dataset_example_id is None:
            raise ValueError("promoted feedback requires a dataset example ID")
        return self
