from enum import Enum

from pydantic import Field, model_validator

from resolveops.models.common import DomainModel, Identifier, NonEmptyText
from resolveops.operations.models import Actor, OperationResult
from resolveops.reasoning.models import ReasoningTrace
from resolveops.workflows.models import PolicyCitation, WorkflowStatus


class EmployeeWorkflowDecision(str, Enum):
    GRANT_ACCESS = "grant_access"
    NO_ACTION = "no_action"
    ESCALATE = "escalate"


class EmployeeWorkflowOutcome(str, Enum):
    ACCESS_VERIFIED = "access_verified"
    ALREADY_SATISFIED = "already_satisfied"
    NEEDS_REVIEW = "needs_review"


class EmployeeAccessWorkflowRequest(DomainModel):
    workflow_id: Identifier
    case_id: Identifier
    actor: Actor


class EmployeeAccessWorkflowResult(DomainModel):
    workflow_id: Identifier
    case_id: Identifier
    status: WorkflowStatus
    outcome: EmployeeWorkflowOutcome
    decision: EmployeeWorkflowDecision
    evidence: list[NonEmptyText] = Field(min_length=1)
    policy_citations: list[PolicyCitation]
    reasoning: ReasoningTrace | None = None
    operation: OperationResult | None = None
    verified_access_id: Identifier | None = None
    resolution_summary: NonEmptyText
    error_code: Identifier | None = None
    error_message: NonEmptyText | None = None
    node_history: list[Identifier] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_terminal_result(self) -> "EmployeeAccessWorkflowResult":
        if self.outcome == EmployeeWorkflowOutcome.ACCESS_VERIFIED and (
            self.status != WorkflowStatus.COMPLETED
            or self.operation is None
            or not self.operation.verified
            or self.verified_access_id != self.operation.resource_id
        ):
            raise ValueError("verified access requires a matching verified operation")
        if self.outcome == EmployeeWorkflowOutcome.ALREADY_SATISFIED and (
            self.status != WorkflowStatus.COMPLETED
            or self.decision != EmployeeWorkflowDecision.NO_ACTION
        ):
            raise ValueError("satisfied access requires a completed no-action decision")
        if self.outcome == EmployeeWorkflowOutcome.NEEDS_REVIEW and self.error_code is None:
            raise ValueError("review outcome requires an error code")
        return self
