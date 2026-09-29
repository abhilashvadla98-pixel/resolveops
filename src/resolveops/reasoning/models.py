from enum import Enum

from pydantic import Field, model_validator

from resolveops.models.case import CaseIssueType
from resolveops.models.common import DomainModel, Identifier, NonEmptyText


class ReasoningConclusion(str, Enum):
    CLAIM_SUPPORTED = "claim_supported"
    CLAIM_NOT_SUPPORTED = "claim_not_supported"
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    ACTION_ALREADY_IN_PROGRESS = "action_already_in_progress"
    POLICY_CONFLICT = "policy_conflict"


class ReasoningDisposition(str, Enum):
    REFUND_CANDIDATE = "refund_candidate"
    ACCESS_CANDIDATE = "access_candidate"
    MONITOR_EXISTING = "monitor_existing"
    MANUAL_REVIEW = "manual_review"
    REJECT_CLAIM = "reject_claim"


class ReasoningEvidence(DomainModel):
    evidence_id: Identifier
    fact: NonEmptyText


class ReasoningPolicyExcerpt(DomainModel):
    chunk_id: Identifier
    document_id: Identifier
    version: int = Field(gt=0)
    section: NonEmptyText
    text: NonEmptyText


class ReasoningContext(DomainModel):
    case_id: Identifier
    issue_id: Identifier
    issue_type: CaseIssueType
    persisted_finding: NonEmptyText
    persisted_status: NonEmptyText
    existing_refund_id: Identifier | None
    evidence: list[ReasoningEvidence] = Field(min_length=1)
    policy_excerpts: list[ReasoningPolicyExcerpt] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_reference_ids(self) -> "ReasoningContext":
        evidence_ids = [item.evidence_id for item in self.evidence]
        chunk_ids = [item.chunk_id for item in self.policy_excerpts]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("reasoning evidence IDs must be unique")
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("reasoning policy chunk IDs must be unique")
        return self


class ReasoningAssessment(DomainModel):
    summary: NonEmptyText
    conclusion: ReasoningConclusion
    recommended_disposition: ReasoningDisposition
    supporting_evidence_ids: list[Identifier] = Field(min_length=1, max_length=20)
    cited_policy_chunk_ids: list[Identifier] = Field(min_length=1, max_length=20)
    missing_information: list[NonEmptyText] = Field(max_length=20)
    risk_notes: list[NonEmptyText] = Field(max_length=20)
    rationale: NonEmptyText

    @model_validator(mode="after")
    def validate_assessment(self) -> "ReasoningAssessment":
        if len(self.supporting_evidence_ids) != len(set(self.supporting_evidence_ids)):
            raise ValueError("supporting evidence references must be unique")
        if len(self.cited_policy_chunk_ids) != len(set(self.cited_policy_chunk_ids)):
            raise ValueError("policy citations must be unique")
        if (
            self.recommended_disposition == ReasoningDisposition.REFUND_CANDIDATE
            and self.conclusion != ReasoningConclusion.CLAIM_SUPPORTED
        ):
            raise ValueError("refund candidate disposition requires a supported claim")
        if (
            self.recommended_disposition == ReasoningDisposition.ACCESS_CANDIDATE
            and self.conclusion != ReasoningConclusion.CLAIM_SUPPORTED
        ):
            raise ValueError("access candidate disposition requires a supported claim")
        if (
            self.recommended_disposition == ReasoningDisposition.MONITOR_EXISTING
            and self.conclusion != ReasoningConclusion.ACTION_ALREADY_IN_PROGRESS
        ):
            raise ValueError("monitor disposition requires an action already in progress")
        if (
            self.recommended_disposition == ReasoningDisposition.REJECT_CLAIM
            and self.conclusion != ReasoningConclusion.CLAIM_NOT_SUPPORTED
        ):
            raise ValueError("reject disposition requires an unsupported claim")
        return self


class ReasoningTrace(DomainModel):
    provider_name: NonEmptyText
    model_name: NonEmptyText
    assessment: ReasoningAssessment
