from enum import Enum

from pydantic import Field, model_validator

from resolveops.models.common import DomainModel, Identifier, NonEmptyText
from resolveops.workflows.models import WorkflowOutcome, WorkflowStatus


class HumanReviewStatus(str, Enum):
    PENDING = "pending_human_review"
    APPROVED = "approved"
    NEEDS_REVISION = "needs_revision"


class ResponseEvaluationCase(DomainModel):
    evaluation_id: Identifier
    title: NonEmptyText
    status: WorkflowStatus
    outcome: WorkflowOutcome
    issue_id: Identifier
    verified_resource_id: Identifier | None = None
    existing_refund_id: Identifier | None = None
    error_code: Identifier | None = None
    required_phrases: list[NonEmptyText] = Field(min_length=1)
    forbidden_phrases: list[NonEmptyText] = Field(min_length=1)
    human_review_status: HumanReviewStatus = HumanReviewStatus.PENDING
    reviewer: NonEmptyText | None = None
    review_note: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_review_and_outcome(self) -> "ResponseEvaluationCase":
        if self.outcome == WorkflowOutcome.ACTION_VERIFIED and self.verified_resource_id is None:
            raise ValueError("verified response case requires a verified resource")
        if self.outcome == WorkflowOutcome.WAITING_EXTERNAL and self.existing_refund_id is None:
            raise ValueError("waiting response case requires an existing refund")
        if self.outcome == WorkflowOutcome.NEEDS_REVIEW and self.error_code is None:
            raise ValueError("review response case requires an error code")
        reviewed = self.human_review_status != HumanReviewStatus.PENDING
        if reviewed != (self.reviewer is not None and self.review_note is not None):
            raise ValueError("completed human review requires reviewer and note")
        return self


class ResponseAssertion(DomainModel):
    name: NonEmptyText
    passed: bool
    detail: NonEmptyText


class ResponseEvaluationResult(DomainModel):
    evaluation_id: Identifier
    title: NonEmptyText
    candidate_message: NonEmptyText
    outcome: WorkflowOutcome
    human_review_status: HumanReviewStatus
    reviewer: NonEmptyText | None
    review_note: NonEmptyText | None
    automated_passed: bool
    assertions: list[ResponseAssertion] = Field(min_length=1)


class ResponseEvaluationReport(DomainModel):
    dataset_name: NonEmptyText
    candidate_count: int = Field(gt=0)
    automated_passed_count: int = Field(ge=0)
    automated_failed_count: int = Field(ge=0)
    human_reviewed_count: int = Field(ge=0)
    human_approved_count: int = Field(ge=0)
    pending_human_review_count: int = Field(ge=0)
    cases: list[ResponseEvaluationResult] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_totals(self) -> "ResponseEvaluationReport":
        if self.automated_passed_count + self.automated_failed_count != self.candidate_count:
            raise ValueError("automated response totals do not match candidate count")
        if self.human_reviewed_count + self.pending_human_review_count != self.candidate_count:
            raise ValueError("human response totals do not match candidate count")
        if len(self.cases) != self.candidate_count:
            raise ValueError("response results do not match candidate count")
        return self
