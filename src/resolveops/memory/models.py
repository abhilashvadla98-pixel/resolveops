from enum import Enum

from pydantic import Field, model_validator

from resolveops.models.common import AwareDatetime, DomainModel, Identifier, NonEmptyText


class MemoryReviewStatus(str, Enum):
    REVIEWED = "reviewed"
    RETIRED = "retired"


class ApprovedResolutionPattern(DomainModel):
    action: Identifier
    requires_approval: bool = True
    notes: NonEmptyText | None = None


class ReviewedResolutionMemory(DomainModel):
    memory_id: Identifier
    tenant_id: Identifier
    issue_type: Identifier
    evidence_pattern: list[NonEmptyText] = Field(min_length=1, max_length=30)
    policy_versions: dict[Identifier, int]
    approved_resolution: ApprovedResolutionPattern
    verification_outcome: NonEmptyText
    human_feedback_id: Identifier | None = None
    review_status: MemoryReviewStatus
    reviewed_by: Identifier
    created_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_reviewed_memory(self) -> "ReviewedResolutionMemory":
        if self.expires_at <= self.created_at:
            raise ValueError("reviewed memory expiry must follow creation")
        if not self.policy_versions or any(
            version < 1 for version in self.policy_versions.values()
        ):
            raise ValueError("reviewed memory requires positive policy versions")
        return self
