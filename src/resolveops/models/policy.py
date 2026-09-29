from enum import Enum
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from resolveops.models.case import CaseIssueType
from resolveops.models.common import AwareDatetime, DomainModel, Identifier, NonEmptyText


class PolicyStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


PolicyContent = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50_000),
]


class Policy(DomainModel):
    policy_id: Identifier
    title: NonEmptyText
    version: int = Field(gt=0)
    status: PolicyStatus
    issue_types: list[CaseIssueType] = Field(min_length=1)
    content: PolicyContent
    source: NonEmptyText
    effective_at: AwareDatetime
    expires_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_policy(self) -> "Policy":
        if len(self.issue_types) != len(set(self.issue_types)):
            raise ValueError("policy issue types must be unique")
        if self.expires_at is not None and self.expires_at <= self.effective_at:
            raise ValueError("expires_at must be later than effective_at")
        return self
