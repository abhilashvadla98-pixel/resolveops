from enum import Enum

from pydantic import Field, model_validator

from resolveops.models.common import (
    CurrencyCode,
    DomainModel,
    Identifier,
    NonEmptyText,
    PositiveAmount,
)
from resolveops.models.refund import RefundKind
from resolveops.operations.models import ActorRole
from resolveops.workflows.models import WorkflowDecision, WorkflowOutcome


class EvaluationCategory(str, Enum):
    SUCCESS = "success"
    AMBIGUOUS = "ambiguous"
    ALREADY_REFUNDED = "already_refunded"
    PERMISSION = "permission"
    POLICY = "policy"
    REASONING = "reasoning"
    TOOL_FAILURE = "tool_failure"


class ScenarioFixture(str, Enum):
    BASELINE = "baseline"
    DUPLICATE_ACTIONABLE = "duplicate_actionable"
    DUPLICATE_SECOND_PAYMENT_PENDING = "duplicate_second_payment_pending"
    DUPLICATE_EXISTING_REFUND = "duplicate_existing_refund"
    RETURN_EXISTING_REFUND = "return_existing_refund"
    RETURN_ACTIONABLE = "return_actionable"
    RETURN_NOT_RECEIVED = "return_not_received"
    REQUIRED_POLICY_MISSING = "required_policy_missing"


class ReasoningBehavior(str, Enum):
    NONE = "none"
    SUPPORT_REFUND = "support_refund"
    MANUAL_REVIEW = "manual_review"
    REJECT_CLAIM = "reject_claim"
    PROVIDER_FAILURE = "provider_failure"
    INVALID_REFERENCE = "invalid_reference"


class ActionBehavior(str, Enum):
    NORMAL = "normal"
    TIMEOUT = "timeout"
    DISAPPEARING_RESOURCE = "disappearing_resource"
    FAILED_VERIFICATION = "failed_verification"


class RefundProposal(DomainModel):
    payment_id: Identifier
    amount: PositiveAmount
    currency: CurrencyCode
    kind: RefundKind
    reason: NonEmptyText
    return_id: Identifier | None = None

    @model_validator(mode="after")
    def validate_return_reference(self) -> "RefundProposal":
        if self.kind == RefundKind.RETURN and self.return_id is None:
            raise ValueError("return evaluation proposals require return_id")
        if self.kind == RefundKind.DUPLICATE_CHARGE and self.return_id is not None:
            raise ValueError("duplicate evaluation proposals cannot include return_id")
        return self


class WorkflowExpectation(DomainModel):
    outcome: WorkflowOutcome
    decision: WorkflowDecision
    error_code: str | None = None
    new_refund_created: bool
    verified: bool
    required_nodes: list[NonEmptyText] = Field(default_factory=list)
    forbidden_nodes: list[NonEmptyText] = Field(default_factory=list)
    required_policy_document_id: Identifier | None = None
    reasoning_grounded: bool | None = None

    @model_validator(mode="after")
    def validate_nodes(self) -> "WorkflowExpectation":
        if set(self.required_nodes).intersection(self.forbidden_nodes):
            raise ValueError("a workflow node cannot be both required and forbidden")
        return self


class WorkflowEvaluationCase(DomainModel):
    evaluation_id: Identifier
    title: NonEmptyText
    category: EvaluationCategory
    issue_id: Identifier
    fixture: ScenarioFixture
    actor_role: ActorRole
    refund_proposal: RefundProposal | None = None
    reasoning_behavior: ReasoningBehavior = ReasoningBehavior.NONE
    action_behavior: ActionBehavior = ActionBehavior.NORMAL
    expected: WorkflowExpectation


class EvaluationAssertion(DomainModel):
    name: NonEmptyText
    expected: str
    actual: str
    passed: bool


class WorkflowObservation(DomainModel):
    outcome: WorkflowOutcome
    decision: WorkflowDecision
    error_code: str | None = None
    new_refund_created: bool
    verified: bool
    node_history: list[NonEmptyText]
    policy_document_ids: list[Identifier]
    reasoning_grounded: bool | None = None


class WorkflowEvaluationResult(DomainModel):
    evaluation_id: Identifier
    title: NonEmptyText
    category: EvaluationCategory
    passed: bool
    assertions: list[EvaluationAssertion] = Field(min_length=1)
    observation: WorkflowObservation | None = None
    execution_error: str | None = None


class CategoryEvaluationMetrics(DomainModel):
    category: EvaluationCategory
    case_count: int = Field(gt=0)
    passed_count: int = Field(ge=0)
    pass_rate: float = Field(ge=0, le=1)


class WorkflowEvaluationReport(DomainModel):
    dataset_name: NonEmptyText
    case_count: int = Field(gt=0)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    pass_rate: float = Field(ge=0, le=1)
    category_metrics: list[CategoryEvaluationMetrics]
    cases: list[WorkflowEvaluationResult]

    @model_validator(mode="after")
    def validate_totals(self) -> "WorkflowEvaluationReport":
        if self.passed_count + self.failed_count != self.case_count:
            raise ValueError("evaluation totals do not match case count")
        if len(self.cases) != self.case_count:
            raise ValueError("evaluation results do not match case count")
        return self
