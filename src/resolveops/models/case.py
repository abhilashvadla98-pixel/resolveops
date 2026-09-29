from enum import Enum

from pydantic import Field, model_validator

from resolveops.models.common import AwareDatetime, DomainModel, Identifier, NonEmptyText


class CaseStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    PENDING_APPROVAL = "pending_approval"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    CLOSED = "closed"


class CaseIssueType(str, Enum):
    DUPLICATE_CHARGE = "duplicate_charge"
    MISSING_RETURN_REFUND = "missing_return_refund"
    REPOSITORY_ACCESS = "repository_access"


class CaseIssueStatus(str, Enum):
    REPORTED = "reported"
    INVESTIGATING = "investigating"
    POLICY_REVIEW = "policy_review"
    ACTION_PENDING = "action_pending"
    ACTION_EXECUTED = "action_executed"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class IssueFinding(str, Enum):
    UNDETERMINED = "undetermined"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class IssueActionStatus(str, Enum):
    PROPOSED = "proposed"
    AUTHORIZED = "authorized"
    EXECUTED = "executed"
    FAILED = "failed"


class VerificationStatus(str, Enum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class CaseIssueEvidence(DomainModel):
    evidence_id: Identifier
    source: NonEmptyText
    reference_id: Identifier
    summary: NonEmptyText
    collected_at: AwareDatetime


class CaseIssueAction(DomainModel):
    action_id: Identifier
    name: NonEmptyText
    status: IssueActionStatus
    created_at: AwareDatetime
    completed_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_completion(self) -> "CaseIssueAction":
        if (
            self.status in {IssueActionStatus.EXECUTED, IssueActionStatus.FAILED}
            and self.completed_at is None
        ):
            raise ValueError("executed and failed actions require completed_at")
        if self.completed_at is not None and self.completed_at < self.created_at:
            raise ValueError("completed_at cannot be earlier than created_at")
        return self


class CaseIssueVerification(DomainModel):
    status: VerificationStatus
    summary: NonEmptyText | None = None
    checked_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_result(self) -> "CaseIssueVerification":
        if self.status != VerificationStatus.PENDING and (
            self.summary is None or self.checked_at is None
        ):
            raise ValueError("completed verification requires a summary and checked_at")
        return self


class CaseIssueResolution(DomainModel):
    summary: NonEmptyText
    resolved_at: AwareDatetime


class CaseIssue(DomainModel):
    issue_id: Identifier
    case_id: Identifier
    order_id: Identifier
    issue_type: CaseIssueType
    status: CaseIssueStatus = CaseIssueStatus.REPORTED
    finding: IssueFinding = IssueFinding.UNDETERMINED
    payment_ids: list[Identifier] = Field(default_factory=list)
    return_id: Identifier | None = None
    evidence: list[CaseIssueEvidence] = Field(default_factory=list)
    actions: list[CaseIssueAction] = Field(default_factory=list)
    verification: CaseIssueVerification | None = None
    resolution: CaseIssueResolution | None = None
    reported_at: AwareDatetime

    @model_validator(mode="after")
    def validate_issue(self) -> "CaseIssue":
        if len(self.payment_ids) != len(set(self.payment_ids)):
            raise ValueError("issue payment IDs must be unique")
        if self.issue_type == CaseIssueType.DUPLICATE_CHARGE and self.return_id is not None:
            raise ValueError("duplicate-charge issues cannot reference a return")

        evidence_ids = [item.evidence_id for item in self.evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("issue evidence must have unique IDs")
        action_ids = [item.action_id for item in self.actions]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("issue actions must have unique IDs")

        if self.status == CaseIssueStatus.RESOLVED:
            if self.finding == IssueFinding.UNDETERMINED:
                raise ValueError("resolved issues require an investigation finding")
            if self.resolution is None:
                raise ValueError("resolved issues require a resolution")
            if self.verification is None or self.verification.status != VerificationStatus.PASSED:
                raise ValueError("resolved issues require successful verification")
        return self


class Case(DomainModel):
    case_id: Identifier
    customer_id: Identifier
    order_id: Identifier
    status: CaseStatus = CaseStatus.OPEN
    issues: list[CaseIssue] = Field(min_length=1)
    opened_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_case(self) -> "Case":
        if self.updated_at < self.opened_at:
            raise ValueError("updated_at cannot be earlier than opened_at")

        issue_ids: set[str] = set()
        for issue in self.issues:
            if issue.issue_id in issue_ids:
                raise ValueError("case issues must have unique IDs")
            if issue.case_id != self.case_id:
                raise ValueError("case issue belongs to a different case")
            if issue.order_id != self.order_id:
                raise ValueError("case issue belongs to a different order")
            issue_ids.add(issue.issue_id)

        if self.status in {CaseStatus.RESOLVED, CaseStatus.CLOSED} and any(
            issue.status != CaseIssueStatus.RESOLVED for issue in self.issues
        ):
            raise ValueError("resolved and closed cases require every issue to be resolved")
        return self
