from enum import Enum

from pydantic import Field, model_validator

from resolveops.employee_it.workflow_models import (
    EmployeeWorkflowDecision,
    EmployeeWorkflowOutcome,
)
from resolveops.evaluation.models import EvaluationAssertion
from resolveops.models.common import DomainModel, Identifier, NonEmptyText
from resolveops.operations.models import ActorRole


class EmployeeEvaluationCategory(str, Enum):
    SUCCESS = "success"
    ELIGIBILITY = "eligibility"
    APPROVAL = "approval"
    PERMISSION = "permission"
    IDEMPOTENCY = "idempotency"
    POLICY = "policy"
    REASONING = "reasoning"


class EmployeeScenarioFixture(str, Enum):
    BASELINE = "baseline"
    INACTIVE_EMPLOYEE = "inactive_employee"
    INACTIVE_IDENTITY = "inactive_identity"
    MISSING_MFA = "missing_mfa"
    MISSING_TEAM = "missing_team"
    INACTIVE_GIT = "inactive_git"
    PENDING_APPROVAL = "pending_approval"
    WRONG_APPROVER = "wrong_approver"
    PARTIAL_ACCESS = "partial_access"
    EXISTING_ACCESS = "existing_access"
    REQUIRED_POLICY_MISSING = "required_policy_missing"


class EmployeeReasoningBehavior(str, Enum):
    NONE = "none"
    SUPPORT_ACCESS = "support_access"
    MANUAL_REVIEW = "manual_review"


class EmployeeWorkflowExpectation(DomainModel):
    outcome: EmployeeWorkflowOutcome
    decision: EmployeeWorkflowDecision
    error_code: Identifier | None = None
    access_created: bool
    verified: bool
    required_policy_document_id: Identifier | None = None


class EmployeeWorkflowEvaluationCase(DomainModel):
    evaluation_id: Identifier
    title: NonEmptyText
    category: EmployeeEvaluationCategory
    fixture: EmployeeScenarioFixture
    actor_role: ActorRole
    reasoning_behavior: EmployeeReasoningBehavior = EmployeeReasoningBehavior.NONE
    expected: EmployeeWorkflowExpectation


class EmployeeWorkflowObservation(DomainModel):
    outcome: EmployeeWorkflowOutcome
    decision: EmployeeWorkflowDecision
    error_code: Identifier | None = None
    access_created: bool
    verified: bool
    policy_document_ids: list[Identifier]


class EmployeeEvaluationResult(DomainModel):
    evaluation_id: Identifier
    title: NonEmptyText
    category: EmployeeEvaluationCategory
    passed: bool
    assertions: list[EvaluationAssertion] = Field(min_length=1)
    observation: EmployeeWorkflowObservation | None = None
    execution_error: str | None = None


class EmployeeCategoryMetrics(DomainModel):
    category: EmployeeEvaluationCategory
    case_count: int = Field(gt=0)
    passed_count: int = Field(ge=0)
    pass_rate: float = Field(ge=0, le=1)


class EmployeeEvaluationReport(DomainModel):
    dataset_name: NonEmptyText
    case_count: int = Field(gt=0)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    pass_rate: float = Field(ge=0, le=1)
    category_metrics: list[EmployeeCategoryMetrics]
    cases: list[EmployeeEvaluationResult]

    @model_validator(mode="after")
    def validate_totals(self) -> "EmployeeEvaluationReport":
        if self.passed_count + self.failed_count != self.case_count:
            raise ValueError("evaluation totals do not match case count")
        if len(self.cases) != self.case_count:
            raise ValueError("evaluation results do not match case count")
        return self
