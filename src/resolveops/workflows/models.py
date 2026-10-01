from decimal import Decimal
from enum import Enum

from pydantic import Field, model_validator

from resolveops.agents.models import MultiAgentReasoningResult
from resolveops.models.case import CaseIssueType, IssueFinding
from resolveops.models.common import AwareDatetime, DomainModel, Identifier, NonEmptyText
from resolveops.operations.models import Actor, ActorRole, IssueRefundRequest, OperationResult
from resolveops.reasoning.models import ReasoningTrace


class WorkflowStatus(str, Enum):
    RECEIVED = "received"
    INVESTIGATING = "investigating"
    POLICY_REVIEW = "policy_review"
    WAITING_APPROVAL = "waiting_approval"
    ACTION_PENDING = "action_pending"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    WAITING_EXTERNAL = "waiting_external"
    ESCALATED = "escalated"


class WorkflowDecision(str, Enum):
    EXECUTE_REFUND = "execute_refund"
    MONITOR_EXISTING_REFUND = "monitor_existing_refund"
    ESCALATE = "escalate"


class WorkflowOutcome(str, Enum):
    ACTION_VERIFIED = "action_verified"
    WAITING_EXTERNAL = "waiting_external"
    NEEDS_REVIEW = "needs_review"


class WorkflowLifecycleStatus(str, Enum):
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    FAILED = "failed"


class WorkflowEventType(str, Enum):
    STARTED = "started"
    CUSTOMER_VERIFIED = "customer_verified"
    ORDER_LOADED = "order_loaded"
    PAYMENT_EVIDENCE_LOADED = "payment_evidence_loaded"
    RETURN_EVIDENCE_LOADED = "return_evidence_loaded"
    POLICY_RETRIEVED = "policy_retrieved"
    ADVISORY_ASSESSED = "advisory_assessed"
    DECISION_RECORDED = "decision_recorded"
    SAFETY_GATE_EVALUATED = "safety_gate_evaluated"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_APPROVED = "approval_approved"
    APPROVAL_REJECTED = "approval_rejected"
    ACTION_EXECUTED = "action_executed"
    ACTION_VERIFIED = "action_verified"
    FINAL_RESPONSE_CREATED = "final_response_created"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    FAILED = "failed"


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalDecisionType(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


class PolicyCitation(DomainModel):
    document_id: Identifier
    version: int = Field(gt=0)
    title: NonEmptyText
    section: NonEmptyText
    source: NonEmptyText
    chunk_id: Identifier
    rank: int = Field(gt=0)


class WorkflowRequest(DomainModel):
    workflow_id: Identifier
    case_id: Identifier
    issue_id: Identifier
    actor: Actor
    refund_request: IssueRefundRequest | None = None

    @model_validator(mode="after")
    def validate_refund_scope(self) -> "WorkflowRequest":
        if self.refund_request is not None and (
            self.refund_request.case_id != self.case_id
            or self.refund_request.issue_id != self.issue_id
        ):
            raise ValueError("refund request must target the workflow case and issue")
        return self


class WorkflowApproval(DomainModel):
    approval_id: Identifier
    workflow_id: Identifier
    case_id: Identifier
    issue_id: Identifier
    status: ApprovalStatus
    payment_id: Identifier
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    reason: NonEmptyText
    requested_by: Identifier
    requested_role: ActorRole
    requested_at: AwareDatetime
    decided_by: Identifier | None = None
    decided_role: ActorRole | None = None
    decision_note: NonEmptyText | None = None
    decided_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> "WorkflowApproval":
        decision_fields = (self.decided_by, self.decided_role, self.decided_at)
        if self.status == ApprovalStatus.PENDING and any(
            value is not None for value in decision_fields
        ):
            raise ValueError("pending approval cannot contain decision fields")
        if self.status != ApprovalStatus.PENDING and any(
            value is None for value in decision_fields
        ):
            raise ValueError("decided approval requires actor, role, and timestamp")
        return self


class WorkflowApprovalDecision(DomainModel):
    approval_id: Identifier
    decision: ApprovalDecisionType
    actor: Actor
    note: NonEmptyText


class WorkflowPause(DomainModel):
    workflow_id: Identifier
    case_id: Identifier
    issue_id: Identifier
    status: WorkflowStatus = WorkflowStatus.WAITING_APPROVAL
    approval: WorkflowApproval
    agent_assessment: MultiAgentReasoningResult | None = None


class WorkflowRun(DomainModel):
    workflow_id: Identifier
    thread_id: Identifier
    case_id: Identifier
    issue_id: Identifier
    status: WorkflowLifecycleStatus
    outcome: WorkflowOutcome | None = None
    requested_by: Identifier
    requested_role: ActorRole
    created_at: AwareDatetime
    updated_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    error_code: Identifier | None = None
    error_message: NonEmptyText | None = None


class WorkflowEvent(DomainModel):
    event_id: Identifier
    workflow_id: Identifier
    sequence_number: int = Field(gt=0)
    event_type: WorkflowEventType
    actor_id: Identifier | None = None
    actor_role: ActorRole | None = None
    details: dict[str, object]
    occurred_at: AwareDatetime


class CustomerResponse(DomainModel):
    message: NonEmptyText
    outcome: WorkflowOutcome
    verified_fact_ids: list[Identifier] = Field(min_length=1)
    policy_citation_ids: list[Identifier]
    generated_at: AwareDatetime

    @model_validator(mode="after")
    def reject_unsupported_completion_claims(self) -> "CustomerResponse":
        normalized = self.message.lower()
        if "refund completed" in normalized or "refund is complete" in normalized:
            raise ValueError("customer response cannot claim final refund completion")
        if self.outcome != WorkflowOutcome.ACTION_VERIFIED and (
            "refund was created" in normalized or "refund has been issued" in normalized
        ):
            raise ValueError("unverified workflow cannot claim that a refund was issued")
        return self


class WorkflowResult(DomainModel):
    workflow_id: Identifier
    case_id: Identifier
    issue_id: Identifier
    status: WorkflowStatus
    outcome: WorkflowOutcome
    issue_type: CaseIssueType
    finding: IssueFinding
    decision: WorkflowDecision
    evidence: list[NonEmptyText]
    policy_citations: list[PolicyCitation]
    reasoning: ReasoningTrace | None = None
    agent_assessment: MultiAgentReasoningResult | None = None
    operation: OperationResult | None = None
    verified_resource_id: Identifier | None = None
    resolution_summary: NonEmptyText
    final_response: CustomerResponse
    error_code: Identifier | None = None
    error_message: NonEmptyText | None = None
    node_history: list[Identifier] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_terminal_result(self) -> "WorkflowResult":
        if self.outcome == WorkflowOutcome.ACTION_VERIFIED and (
            self.status != WorkflowStatus.COMPLETED
            or self.operation is None
            or not self.operation.verified
            or self.verified_resource_id != self.operation.resource_id
        ):
            raise ValueError("verified action outcome requires a matching verified operation")
        if self.outcome == WorkflowOutcome.NEEDS_REVIEW and self.error_code is None:
            raise ValueError("review outcome requires an error code")
        return self
