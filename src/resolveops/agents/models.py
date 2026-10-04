from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from resolveops.models.case import CaseIssueType
from resolveops.models.common import AwareDatetime, DomainModel, Identifier, NonEmptyText


class AgentRole(str, Enum):
    SUPERVISOR = "supervisor"
    INVESTIGATION = "investigation"
    POLICY = "policy"
    RESOLUTION = "resolution"
    CRITIC = "critic"


class AgentDomain(str, Enum):
    CUSTOMER_OPERATIONS = "customer_operations"
    EMPLOYEE_IT = "employee_it"


class AgentRunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BUDGET_EXCEEDED = "budget_exceeded"


class CriticDecision(str, Enum):
    ACCEPT = "accept"
    REVISE = "revise"
    ESCALATE = "escalate"


class ToolCallStatus(str, Enum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"


class EvidenceFact(DomainModel):
    evidence_id: Identifier
    fact: NonEmptyText
    source: NonEmptyText
    observed_at: AwareDatetime
    fresh: bool = True
    source_field: str | None = Field(default=None, max_length=500)
    source_value_json: str | None = Field(default=None, max_length=2_000)


class PlanStep(DomainModel):
    step_id: Identifier
    objective: NonEmptyText
    assigned_role: AgentRole
    depends_on: list[Identifier] = Field(default_factory=list, max_length=20)
    can_run_in_parallel: bool = False


class SupervisorPlan(DomainModel):
    goal: NonEmptyText
    issues: list[NonEmptyText] = Field(min_length=1, max_length=20)
    plan_steps: list[PlanStep] = Field(min_length=1, max_length=20)
    required_evidence: list[NonEmptyText] = Field(max_length=30)
    delegations: list[AgentRole] = Field(min_length=1, max_length=10)
    parallelizable_tasks: list[Identifier] = Field(max_length=20)
    missing_information: list[NonEmptyText] = Field(max_length=20)
    next_agent: AgentRole
    stopping_condition: NonEmptyText
    escalation_reason: NonEmptyText | None = None


class ToolArguments(DomainModel):
    """Finite read-tool inputs so provider schemas never contain an untyped object."""

    resource_id: Identifier | None = None
    case_id: Identifier | None = None
    customer_id: Identifier | None = None
    order_id: Identifier | None = None
    payment_id: Identifier | None = None
    return_id: Identifier | None = None
    refund_id: Identifier | None = None
    it_case_id: Identifier | None = None
    query: NonEmptyText | None = None
    issue_type: CaseIssueType | None = None
    top_k: int | None = Field(default=None, ge=1, le=10)


class ToolRequest(DomainModel):
    tool_name: Identifier
    arguments: ToolArguments = Field(default_factory=ToolArguments)
    purpose: NonEmptyText


class InvestigationTurn(DomainModel):
    facts: list[EvidenceFact] = Field(default_factory=list, max_length=50)
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=50)
    contradictions: list[NonEmptyText] = Field(default_factory=list, max_length=20)
    missing_evidence: list[NonEmptyText] = Field(default_factory=list, max_length=20)
    confidence: float = Field(ge=0, le=1)
    recommended_next_investigation: NonEmptyText | None = None
    source_provenance: list[NonEmptyText] = Field(default_factory=list, max_length=50)
    next_tool: ToolRequest | None = None
    complete: bool

    @model_validator(mode="after")
    def validate_stop_contract(self) -> "InvestigationTurn":
        if self.complete and self.next_tool is not None:
            raise ValueError("a completed investigation cannot request another tool")
        if not self.complete and self.next_tool is None:
            raise ValueError("an incomplete investigation must request its next tool")
        return self


class PolicyVersionReference(DomainModel):
    policy_id: Identifier
    version: int = Field(gt=0)


class PolicyTurn(DomainModel):
    applicable_policy: NonEmptyText | None = None
    citations: list[Identifier] = Field(default_factory=list, max_length=30)
    policy_versions: dict[Identifier, int] = Field(default_factory=dict)
    selected_policy_versions: list[PolicyVersionReference] = Field(
        default_factory=list, max_length=30
    )
    supporting_sections: list[NonEmptyText] = Field(default_factory=list, max_length=30)
    conflicts: list[NonEmptyText] = Field(default_factory=list, max_length=20)
    missing_policy: bool = False
    policy_interpretation: NonEmptyText
    uncertainty: list[NonEmptyText] = Field(default_factory=list, max_length=20)
    next_query: NonEmptyText | None = None
    complete: bool

    @model_validator(mode="after")
    def validate_stop_contract(self) -> "PolicyTurn":
        if self.selected_policy_versions:
            selected = {item.policy_id: item.version for item in self.selected_policy_versions}
            if len(selected) != len(self.selected_policy_versions):
                raise ValueError("policy version references must be unique")
            if self.policy_versions and self.policy_versions != selected:
                raise ValueError("policy version representations disagree")
            if not self.policy_versions:
                self.policy_versions = selected
        if self.complete and self.next_query is not None:
            raise ValueError("a completed policy assessment cannot request another query")
        if not self.complete and self.next_query is None:
            raise ValueError("an incomplete policy assessment must provide a follow-up query")
        return self


class ProposedAction(DomainModel):
    action_type: Identifier
    issue_id: Identifier
    resource_id: Identifier | None = None
    amount: str | None = None
    requires_approval: bool


class IssueResolution(DomainModel):
    issue_id: Identifier
    disposition: Literal["refund", "wait", "no_action", "request_information", "escalate"] = (
        "escalate"
    )
    recommendation: NonEmptyText
    clarification_question: NonEmptyText | None = None
    evidence_ids: list[Identifier] = Field(min_length=1, max_length=30)
    policy_citations: list[Identifier] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def clarification_requires_question(self) -> "IssueResolution":
        if self.disposition == "request_information" and not self.clarification_question:
            raise ValueError("request_information requires a specific clarification question")
        return self


class ResolutionProposal(DomainModel):
    issue_resolutions: list[IssueResolution] = Field(min_length=1, max_length=20)
    proposed_actions: list[ProposedAction] = Field(default_factory=list, max_length=20)
    evidence_support: list[Identifier] = Field(min_length=1, max_length=50)
    policy_support: list[Identifier] = Field(default_factory=list, max_length=30)
    risk_flags: list[NonEmptyText] = Field(default_factory=list, max_length=20)
    uncertainty: list[NonEmptyText] = Field(default_factory=list, max_length=20)
    escalation_needed: bool


class CriticReport(DomainModel):
    decision: CriticDecision
    unsupported_claims: list[NonEmptyText] = Field(default_factory=list, max_length=20)
    missing_evidence: list[NonEmptyText] = Field(default_factory=list, max_length=20)
    contradictions: list[NonEmptyText] = Field(default_factory=list, max_length=20)
    unsafe_actions: list[NonEmptyText] = Field(default_factory=list, max_length=20)
    citation_issues: list[NonEmptyText] = Field(default_factory=list, max_length=20)
    expected_state_reached: bool | None = None
    partial_completion: list[NonEmptyText] = Field(default_factory=list, max_length=20)
    summary: NonEmptyText

    @model_validator(mode="after")
    def validate_acceptance(self) -> "CriticReport":
        findings = (
            self.unsupported_claims
            + self.missing_evidence
            + self.contradictions
            + self.unsafe_actions
            + self.citation_issues
            + self.partial_completion
        )
        if self.decision == CriticDecision.ACCEPT and findings:
            raise ValueError("an accepting critic cannot report unresolved findings")
        return self


class AgentBudget(DomainModel):
    max_agent_steps: int = Field(default=8, ge=5, le=30)
    max_model_calls: int = Field(default=8, ge=5, le=30)
    max_tool_calls: int = Field(default=12, ge=1, le=50)
    max_input_tokens: int = Field(default=24_000, ge=1_000, le=250_000)
    max_output_tokens: int = Field(default=4_000, ge=500, le=50_000)
    max_wall_clock_seconds: int = Field(default=90, ge=10, le=900)
    max_replans: int = Field(default=2, ge=0, le=5)
    optional_cost_limit_usd: float | None = Field(default=None, gt=0, le=100)


class AgentBudgetUsage(DomainModel):
    agent_steps: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)


class SharedAgentState(DomainModel):
    workflow_id: Identifier
    case_id: Identifier
    tenant_id: Identifier
    domain: AgentDomain
    issue_ids: list[Identifier] = Field(min_length=1, max_length=20)
    goal: NonEmptyText
    plan: SupervisorPlan | None = None
    current_step: Identifier = "intake"
    evidence: list[EvidenceFact] = Field(default_factory=list, max_length=200)
    evidence_provenance: list[NonEmptyText] = Field(default_factory=list, max_length=200)
    missing_evidence: list[NonEmptyText] = Field(default_factory=list, max_length=50)
    investigation_summary: InvestigationTurn | None = None
    policy_summary: PolicyTurn | None = None
    resolution: ResolutionProposal | None = None
    critic_findings: list[CriticReport] = Field(default_factory=list, max_length=10)
    approval_state: Literal["not_required", "pending", "approved", "rejected"] = "not_required"
    action_intent: list[ProposedAction] = Field(default_factory=list, max_length=20)
    action_result: dict[str, str] | None = None
    verification_result: CriticReport | None = None
    retry_count: int = Field(default=0, ge=0)
    replan_count: int = Field(default=0, ge=0)
    agent_call_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    budget: AgentBudget = Field(default_factory=AgentBudget)
    usage: AgentBudgetUsage = Field(default_factory=AgentBudgetUsage)
    trace_id: Identifier
    started_at: AwareDatetime
    deadline: AwareDatetime
    error_code: Identifier | None = None
    escalation_reason: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_deadline(self) -> "SharedAgentState":
        if self.deadline <= self.started_at:
            raise ValueError("agent workflow deadline must follow its start time")
        return self


class AgentInvocationRecord(DomainModel):
    agent_run_id: Identifier
    workflow_id: Identifier
    tenant_id: Identifier
    role: AgentRole
    parent_agent_run_id: Identifier | None = None
    prompt_version: Identifier
    schema_version: Identifier
    provider: NonEmptyText
    model: NonEmptyText
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    status: AgentRunStatus
    latency_ms: float | None = Field(default=None, ge=0)
    context_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    structured_output: dict[str, object] | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    error_classification: Identifier | None = None
    trace_id: Identifier


class ToolCallRecord(DomainModel):
    tool_call_id: Identifier
    tenant_id: Identifier
    agent_run_id: Identifier
    tool_name: Identifier
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    status: ToolCallStatus
    latency_ms: float | None = Field(default=None, ge=0)
    argument_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    argument_keys: list[Identifier] = Field(default_factory=list, max_length=20)
    result_category: Identifier | None = None
    error_classification: Identifier | None = None


class MultiAgentReasoningResult(DomainModel):
    workflow_id: Identifier
    case_id: Identifier
    tenant_id: Identifier
    domain: AgentDomain
    supervisor: SupervisorPlan
    investigation: InvestigationTurn
    policy: PolicyTurn | None
    resolution: ResolutionProposal | None
    critic: CriticReport | None
    skipped_roles: list[AgentRole] = Field(default_factory=list, max_length=3)
    stop_reason: NonEmptyText | None = None
    status: Literal["ready_for_control_plane", "escalated"]
    replan_count: int = Field(ge=0)
    agent_call_count: int = Field(ge=1)
    tool_call_count: int = Field(ge=0)
    usage: AgentBudgetUsage
    agent_run_ids: list[Identifier] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def validate_skipped_roles(self) -> "MultiAgentReasoningResult":
        absent = {
            role
            for role, output in (
                (AgentRole.POLICY, self.policy),
                (AgentRole.RESOLUTION, self.resolution),
                (AgentRole.CRITIC, self.critic),
            )
            if output is None
        }
        if absent != set(self.skipped_roles):
            raise ValueError("null role outputs must exactly match explicit skipped roles")
        if absent and (self.status != "escalated" or self.stop_reason is None):
            raise ValueError("skipped roles require an escalated result and stop reason")
        if self.status == "ready_for_control_plane" and (
            absent or self.critic is None or self.critic.decision != CriticDecision.ACCEPT
        ):
            raise ValueError("control-plane readiness requires all roles and critic acceptance")
        return self
