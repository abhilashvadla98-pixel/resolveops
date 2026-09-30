import operator
from typing import Annotated, NotRequired, TypedDict

from resolveops.agents.models import MultiAgentReasoningResult
from resolveops.models.case import CaseIssueType, IssueFinding
from resolveops.operations.models import Actor, IssueRefundRequest, OperationResult
from resolveops.reasoning.models import ReasoningPolicyExcerpt, ReasoningTrace
from resolveops.workflows.models import (
    PolicyCitation,
    WorkflowApproval,
    WorkflowDecision,
    WorkflowOutcome,
    WorkflowStatus,
)


class WorkflowState(TypedDict):
    workflow_id: str
    case_id: str
    issue_id: str
    actor: Actor
    refund_request: IssueRefundRequest | None
    status: WorkflowStatus
    evidence: list[str]
    policy_citations: list[PolicyCitation]
    policy_excerpts: list[ReasoningPolicyExcerpt]
    node_history: Annotated[list[str], operator.add]
    issue_type: NotRequired[CaseIssueType]
    issue_status: NotRequired[str]
    finding: NotRequired[IssueFinding]
    order_id: NotRequired[str]
    customer_id: NotRequired[str]
    complaint_text: NotRequired[str | None]
    case_issue_count: NotRequired[int]
    payment_ids: NotRequired[list[str]]
    return_id: NotRequired[str | None]
    existing_refund_id: NotRequired[str | None]
    decision: NotRequired[WorkflowDecision]
    reasoning: NotRequired[ReasoningTrace | None]
    agent_assessment: NotRequired[MultiAgentReasoningResult | None]
    operation: NotRequired[OperationResult | None]
    verified_resource_id: NotRequired[str | None]
    outcome: NotRequired[WorkflowOutcome]
    resolution_summary: NotRequired[str]
    error_code: NotRequired[str | None]
    error_message: NotRequired[str | None]
    approval: NotRequired[WorkflowApproval | None]
