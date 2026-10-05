import operator
from typing import Annotated, NotRequired, TypedDict

from resolveops.agents.models import MultiAgentReasoningResult
from resolveops.employee_it.models import (
    EmployeeAccessSnapshot,
    GrantRepositoryAccessRequest,
)
from resolveops.employee_it.workflow_models import (
    EmployeeWorkflowDecision,
    EmployeeWorkflowOutcome,
)
from resolveops.operations.models import Actor, OperationResult
from resolveops.reasoning.models import ReasoningPolicyExcerpt, ReasoningTrace
from resolveops.workflows.models import PolicyCitation, WorkflowStatus


class EmployeeAccessWorkflowState(TypedDict):
    workflow_id: str
    case_id: str
    actor: Actor
    status: WorkflowStatus
    evidence: list[str]
    policy_citations: list[PolicyCitation]
    policy_excerpts: list[ReasoningPolicyExcerpt]
    node_history: Annotated[list[str], operator.add]
    snapshot: NotRequired[EmployeeAccessSnapshot]
    eligibility_error_code: NotRequired[str | None]
    eligibility_error_message: NotRequired[str | None]
    already_satisfied: NotRequired[bool]
    access_request: NotRequired[GrantRepositoryAccessRequest]
    decision: NotRequired[EmployeeWorkflowDecision]
    reasoning: NotRequired[ReasoningTrace | None]
    agent_assessment: NotRequired[MultiAgentReasoningResult | None]
    agent_attempted: NotRequired[bool]
    operation: NotRequired[OperationResult | None]
    verified_access_id: NotRequired[str | None]
    outcome: NotRequired[EmployeeWorkflowOutcome]
    resolution_summary: NotRequired[str]
    error_code: NotRequired[str | None]
    error_message: NotRequired[str | None]
