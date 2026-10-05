import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, cast

from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from resolveops.agents.budgets import AgentBudgetExceeded
from resolveops.agents.models import AgentDomain, CriticDecision, MultiAgentReasoningResult
from resolveops.database.employee_it_records import (
    ITAccessCaseRecord,
    ITAccessRequestRecord,
    ITTicketRecord,
)
from resolveops.employee_it.models import (
    AccessRequestStatus,
    EmploymentStatus,
    GitAccountStatus,
    GrantRepositoryAccessRequest,
    IdentityStatus,
    ITCaseStatus,
    ITNotificationStatus,
    ITTicketStatus,
    MembershipStatus,
    RepositoryAccessLevel,
)
from resolveops.employee_it.store import EmployeeITStore
from resolveops.employee_it.workflow_models import (
    EmployeeAccessWorkflowRequest,
    EmployeeAccessWorkflowResult,
    EmployeeWorkflowDecision,
    EmployeeWorkflowOutcome,
)
from resolveops.employee_it.workflow_state import EmployeeAccessWorkflowState
from resolveops.knowledge.embeddings import EmbeddingProvider
from resolveops.knowledge.retrieval import HybridPolicyRetriever
from resolveops.models.case import CaseIssueType
from resolveops.observability.models import TraceComponent
from resolveops.observability.sinks import DEFAULT_TRACE_SINK, TraceSink
from resolveops.observability.tracing import current_trace_id, observed_span, trace_context
from resolveops.operations.actions import ActionTools
from resolveops.operations.errors import OperationError
from resolveops.operations.models import OperationStatus
from resolveops.reasoning.agent import CaseReasoner
from resolveops.reasoning.errors import ReasoningError, ReasoningProviderError
from resolveops.reasoning.models import ReasoningDisposition, ReasoningPolicyExcerpt
from resolveops.reasoning.providers import ReasoningProvider
from resolveops.workflows.models import PolicyCitation, WorkflowStatus

POLICY_QUERY = (
    "active employee identity MFA target team membership manager approval "
    "directory group least privilege repository access verification"
)
REQUIRED_POLICY = "POLICY-REPOSITORY-ACCESS"
LOGGER = logging.getLogger(__name__)


class IntegratedAgentRuntime(Protocol):
    def run(
        self,
        *,
        workflow_id: str,
        case_id: str,
        tenant_id: str,
        domain: AgentDomain,
        objective: str,
        trace_id: str,
    ) -> MultiAgentReasoningResult: ...


class EmployeeAccessWorkflow:
    """Policy-grounded access workflow with deterministic authorization gates."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        embedding_provider: EmbeddingProvider,
        *,
        action_tools: ActionTools | None = None,
        reasoning_provider: ReasoningProvider | None = None,
        agent_runtime: IntegratedAgentRuntime | None = None,
        tenant_id: str = "TENANT-LOCAL",
        model_execution_mode: str = "live_model",
        observability_sink: TraceSink | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.embedding_provider = embedding_provider
        self.observability_sink = observability_sink or DEFAULT_TRACE_SINK
        self.agent_runtime = agent_runtime
        self.tenant_id = tenant_id
        self.model_execution_mode = model_execution_mode
        self.action_tools = action_tools or ActionTools(
            session_factory, observability_sink=self.observability_sink
        )
        self.reasoner = (
            CaseReasoner(reasoning_provider, observability_sink=self.observability_sink)
            if reasoning_provider
            else None
        )
        self.clock = clock or (lambda: datetime.now(UTC))
        self.graph = self._build_graph()

    def run(self, request: EmployeeAccessWorkflowRequest) -> EmployeeAccessWorkflowResult:
        initial: EmployeeAccessWorkflowState = {
            "workflow_id": request.workflow_id,
            "case_id": request.case_id,
            "actor": request.actor,
            "status": WorkflowStatus.RECEIVED,
            "evidence": [],
            "policy_citations": [],
            "policy_excerpts": [],
            "node_history": [],
            "agent_assessment": None,
        }
        with (
            trace_context(
                self.observability_sink,
                workflow_id=request.workflow_id,
                case_id=request.case_id,
            ),
            observed_span(
                TraceComponent.WORKFLOW,
                "employee_access_run",
                sink=self.observability_sink,
            ) as span,
        ):
            final = cast(EmployeeAccessWorkflowState, self.graph.invoke(initial))
            result = self._result(final)
            span.set_attribute("outcome", result.outcome.value)
            span.set_attribute("final_status", result.status.value)
            return result

    def _build_graph(
        self,
    ) -> CompiledStateGraph[
        EmployeeAccessWorkflowState,
        None,
        EmployeeAccessWorkflowState,
        EmployeeAccessWorkflowState,
    ]:
        builder = StateGraph(EmployeeAccessWorkflowState)
        for name, node in (
            ("load_case", self._load_case),
            ("inspect_eligibility", self._inspect_eligibility),
            ("inspect_access", self._inspect_access),
            ("retrieve_policy", self._retrieve_policy),
            ("reason_case", self._reason_case),
            ("decide", self._decide),
            ("grant_access", self._grant_access),
            ("verify_access", self._verify_access),
            ("complete", self._complete),
            ("already_satisfied", self._already_satisfied),
            ("escalate", self._escalate),
        ):
            builder.add_node(name, self._observed_node(name, node))
        builder.add_edge(START, "load_case")
        builder.add_edge("load_case", "inspect_eligibility")
        builder.add_edge("inspect_eligibility", "inspect_access")
        builder.add_edge("inspect_access", "retrieve_policy")
        builder.add_edge("retrieve_policy", "reason_case")
        builder.add_conditional_edges(
            "reason_case",
            lambda state: "escalate" if state["status"] == WorkflowStatus.ESCALATED else "decide",
            {"decide": "decide", "escalate": "escalate"},
        )
        builder.add_conditional_edges(
            "decide",
            lambda state: state["decision"].value,
            {
                EmployeeWorkflowDecision.GRANT_ACCESS.value: "grant_access",
                EmployeeWorkflowDecision.NO_ACTION.value: "already_satisfied",
                EmployeeWorkflowDecision.ESCALATE.value: "escalate",
            },
        )
        builder.add_conditional_edges(
            "grant_access",
            lambda state: "verify" if state.get("operation") is not None else "escalate",
            {"verify": "verify_access", "escalate": "escalate"},
        )
        builder.add_conditional_edges(
            "verify_access",
            lambda state: "complete" if state.get("verified_access_id") is not None else "escalate",
            {"complete": "complete", "escalate": "escalate"},
        )
        builder.add_edge("complete", END)
        builder.add_edge("already_satisfied", END)
        builder.add_edge("escalate", END)
        return builder.compile(name="resolveops-employee-access")

    def _observed_node(
        self,
        name: str,
        node: Callable[[EmployeeAccessWorkflowState], dict[str, object]],
    ) -> RunnableLambda[EmployeeAccessWorkflowState, dict[str, object]]:
        def invoke(state: EmployeeAccessWorkflowState) -> dict[str, object]:
            with observed_span(
                TraceComponent.WORKFLOW_NODE,
                name,
                sink=self.observability_sink,
            ) as span:
                result = node(state)
                status = result.get("status")
                if isinstance(status, WorkflowStatus):
                    span.set_attribute("status", status.value)
                return result

        return RunnableLambda(invoke, name=name)

    def _load_case(self, state: EmployeeAccessWorkflowState) -> dict[str, object]:
        with self.session_factory() as session:
            snapshot = EmployeeITStore(session).get_snapshot(state["case_id"])
        evidence = [
            f"Employee {snapshot.employee.employee_id} status is {snapshot.employee.status.value}.",
            f"Identity {snapshot.identity.identity_id} status is {snapshot.identity.status.value}.",
            f"Target team is {snapshot.team.name} ({snapshot.team.team_id}).",
            (
                f"Git account {snapshot.git_account.git_account_id} status is "
                f"{snapshot.git_account.status.value}."
            ),
            (
                f"Access request {snapshot.access_request.access_request_id} status is "
                f"{snapshot.access_request.status.value}."
            ),
        ]
        return {
            "snapshot": snapshot,
            "status": WorkflowStatus.INVESTIGATING,
            "evidence": evidence,
            "node_history": ["load_case"],
        }

    @staticmethod
    def _inspect_eligibility(state: EmployeeAccessWorkflowState) -> dict[str, object]:
        snapshot = state["snapshot"]
        checks = (
            (
                snapshot.access_request.requested_level
                in {RepositoryAccessLevel.READ, RepositoryAccessLevel.WRITE},
                "access_level_not_supported",
                "This workflow permits read or write repository access only.",
            ),
            (
                snapshot.employee.status == EmploymentStatus.ACTIVE,
                "employee_inactive",
                "Employee must be active.",
            ),
            (
                snapshot.identity.employee_id == snapshot.employee.employee_id
                and snapshot.identity.status == IdentityStatus.ACTIVE,
                "identity_ineligible",
                "Enterprise identity must be active and owned by the employee.",
            ),
            (snapshot.identity.mfa_enrolled, "mfa_required", "MFA enrollment is required."),
            (
                snapshot.team_membership is not None
                and snapshot.team_membership.status == MembershipStatus.ACTIVE,
                "team_membership_required",
                "Active target-team membership is required.",
            ),
            (
                snapshot.git_account.identity_id == snapshot.identity.identity_id
                and snapshot.git_account.status == GitAccountStatus.ACTIVE,
                "git_account_inactive",
                "Git account must be active and linked to the enterprise identity.",
            ),
            (
                snapshot.repository.owning_team_id == snapshot.team.team_id,
                "repository_policy_mismatch",
                "Repository must be owned by the target team.",
            ),
        )
        failure = next(((code, message) for ok, code, message in checks if not ok), None)
        return {
            "eligibility_error_code": failure[0] if failure else None,
            "eligibility_error_message": failure[1] if failure else None,
            "evidence": [
                *state["evidence"],
                "Deterministic employment, identity, MFA, team, and Git checks completed.",
            ],
            "node_history": ["inspect_eligibility"],
        }

    @staticmethod
    def _inspect_access(state: EmployeeAccessWorkflowState) -> dict[str, object]:
        snapshot = state["snapshot"]
        group_active = (
            snapshot.group_membership is not None
            and snapshot.group_membership.status == MembershipStatus.ACTIVE
        )
        access_active = (
            snapshot.repository_access is not None
            and snapshot.repository_access.status == MembershipStatus.ACTIVE
        )
        exact_access = (
            group_active
            and access_active
            and snapshot.repository_access is not None
            and snapshot.repository_access.level == snapshot.access_request.requested_level
        )
        code = state.get("eligibility_error_code")
        message = state.get("eligibility_error_message")
        if not exact_access and (
            snapshot.repository_access is not None or snapshot.group_membership is not None
        ):
            code = "existing_access_conflict"
            message = "Existing access is partial, inactive or at a different level; an operator must reconcile it."
        fact = (
            "Requested repository access and required group membership already exist."
            if exact_access
            else "Requested repository access is not fully provisioned."
        )
        return {
            "already_satisfied": exact_access,
            "eligibility_error_code": code,
            "eligibility_error_message": message,
            "evidence": [*state["evidence"], fact],
            "node_history": ["inspect_access"],
        }

    def _retrieve_policy(self, state: EmployeeAccessWorkflowState) -> dict[str, object]:
        with self.session_factory() as session:
            results = HybridPolicyRetriever(
                session,
                self.embedding_provider,
                observability_sink=self.observability_sink,
            ).search(
                POLICY_QUERY,
                as_of=self.clock(),
                issue_type=CaseIssueType.REPOSITORY_ACCESS,
                top_k=3,
            )
        return {
            "status": WorkflowStatus.POLICY_REVIEW,
            "policy_citations": [
                PolicyCitation(
                    document_id=item.document_id,
                    version=item.document_version,
                    title=item.title,
                    section=item.heading,
                    source=item.source,
                    chunk_id=item.chunk_id,
                    rank=item.rank,
                )
                for item in results
            ],
            "policy_excerpts": [
                ReasoningPolicyExcerpt(
                    chunk_id=item.chunk_id,
                    document_id=item.document_id,
                    version=item.document_version,
                    section=item.heading,
                    text=item.text,
                )
                for item in results
            ],
            "node_history": ["retrieve_policy"],
        }

    def _reason_case(self, state: EmployeeAccessWorkflowState) -> dict[str, object]:
        snapshot = state["snapshot"]
        request = snapshot.access_request
        approved = (
            request.status in {AccessRequestStatus.APPROVED, AccessRequestStatus.FULFILLED}
            and request.approved_by == snapshot.team.manager_employee_id
            and request.approved_at is not None
            and request.approved_by != snapshot.employee.employee_id
        )
        # Avoid model spend when deterministic state already decides the case.
        if state.get("already_satisfied") or not approved:
            return {"reasoning": None, "node_history": ["reason_case"]}
        if self.agent_runtime is not None:
            try:
                assessment = self.agent_runtime.run(
                    workflow_id=state["workflow_id"],
                    case_id=state["case_id"],
                    tenant_id=self.tenant_id,
                    domain=AgentDomain.EMPLOYEE_IT,
                    objective=(
                        f"Investigate repository access request "
                        f"{snapshot.access_request.access_request_id} for "
                        f"{snapshot.repository.repository_id}. "
                        f"Requested level: {snapshot.access_request.requested_level.value}. "
                        f"Justification: {snapshot.access_request.justification}"
                    ),
                    trace_id=current_trace_id() or state["workflow_id"],
                )
            except (AgentBudgetExceeded, ReasoningProviderError, ValueError) as exc:
                diagnostic = (
                    exc.errors(include_input=False, include_context=False)
                    if isinstance(exc, ValidationError)
                    else str(exc)
                )
                LOGGER.warning(
                    "Employee IT agent assessment stopped for workflow %s (%s): %s",
                    state["workflow_id"],
                    type(exc).__name__,
                    diagnostic,
                )
                return {
                    "status": WorkflowStatus.ESCALATED,
                    "agent_assessment": None,
                    "agent_attempted": True,
                    "error_code": "multi_agent_analysis_failed",
                    "error_message": (
                        "The specialist assessment stopped safely before access controls: "
                        f"{type(exc).__name__}."
                    ),
                    "node_history": ["reason_case"],
                }
            if assessment.status != "ready_for_control_plane":
                return {
                    "status": WorkflowStatus.ESCALATED,
                    "agent_assessment": assessment,
                    "agent_attempted": True,
                    "error_code": "multi_agent_review_required",
                    "error_message": (
                        "The independent critic did not clear the access recommendation."
                    ),
                    "node_history": ["reason_case"],
                }
            return {
                "agent_assessment": assessment,
                "agent_attempted": True,
                "reasoning": None,
                "node_history": ["reason_case"],
            }
        if self.reasoner is None or not state["policy_excerpts"]:
            return {"reasoning": None, "node_history": ["reason_case"]}
        try:
            reasoning = self.reasoner.reason(
                case_id=state["case_id"],
                issue_id=snapshot.access_request.access_request_id,
                issue_type=CaseIssueType.REPOSITORY_ACCESS,
                persisted_finding=(
                    "access_missing" if not state.get("already_satisfied") else "access_present"
                ),
                persisted_status=snapshot.access_case.status.value,
                existing_refund_id=None,
                evidence=state["evidence"],
                policy_excerpts=state["policy_excerpts"],
            )
        except ReasoningError as exc:
            return {
                "status": WorkflowStatus.ESCALATED,
                "error_code": exc.code,
                "error_message": exc.message,
                "node_history": ["reason_case"],
            }
        return {"reasoning": reasoning, "node_history": ["reason_case"]}

    def _decide(self, state: EmployeeAccessWorkflowState) -> dict[str, object]:
        snapshot = state["snapshot"]
        if not any(
            citation.document_id == REQUIRED_POLICY for citation in state["policy_citations"]
        ):
            return self._review(
                "required_policy_not_found",
                f"Active policy {REQUIRED_POLICY} was not retrieved.",
            )
        if state.get("eligibility_error_code") is not None:
            return self._review(
                cast(str, state["eligibility_error_code"]),
                cast(str, state["eligibility_error_message"]),
            )
        request = snapshot.access_request
        if (
            request.status not in {AccessRequestStatus.APPROVED, AccessRequestStatus.FULFILLED}
            or request.approved_by != snapshot.team.manager_employee_id
            or request.approved_at is None
            or request.approved_by == snapshot.employee.employee_id
        ):
            return self._review(
                "manager_approval_required",
                "The target-team manager must approve the access request.",
            )
        if state.get("already_satisfied"):
            return {
                "decision": EmployeeWorkflowDecision.NO_ACTION,
                "status": WorkflowStatus.COMPLETED,
                "node_history": ["decide"],
            }
        if snapshot.access_case.status not in {ITCaseStatus.ACTION_PENDING, ITCaseStatus.ESCALATED}:
            return self._review(
                "case_not_actionable", "IT case must be approved or awaiting recovery."
            )
        assessment = state.get("agent_assessment")
        if assessment is not None:
            resolution = assessment.resolution
            recommendation = (
                next(
                    (
                        item
                        for item in resolution.issue_resolutions
                        if item.issue_id == request.access_request_id
                    ),
                    None,
                )
                if resolution is not None
                else None
            )
            if (
                assessment.case_id != state["case_id"]
                or assessment.tenant_id != self.tenant_id
                or assessment.domain != AgentDomain.EMPLOYEE_IT
                or assessment.critic is None
                or assessment.critic.decision != CriticDecision.ACCEPT
                or resolution is None
                or resolution.escalation_needed
                or resolution.uncertainty
                or recommendation is None
            ):
                return self._review(
                    "agent_proposal_requires_review",
                    "The specialist recommendation is incomplete, uncertain or requires review.",
                )
            if recommendation.disposition in {"escalate", "request_information"}:
                return self._review(
                    "agent_requires_information",
                    recommendation.clarification_question or recommendation.recommendation,
                )
            proposed = [
                item
                for item in resolution.proposed_actions
                if item.issue_id == request.access_request_id
            ]
            supported = (
                recommendation.disposition == "access"
                and len(proposed) == 1
                and proposed[0].action_type == "grant_repository_access"
                and proposed[0].resource_id == snapshot.repository.repository_id
                and proposed[0].amount is None
                and proposed[0].requires_approval
            )
            if not supported:
                return self._review(
                    "agent_action_mismatch",
                    "The specialist action did not exactly match the approved access request.",
                )
        reasoning = state.get("reasoning")
        if reasoning is not None and (
            reasoning.assessment.recommended_disposition != ReasoningDisposition.ACCESS_CANDIDATE
        ):
            return self._review(
                "reasoning_recommends_review",
                "Advisory reasoning did not support access; execution was stopped.",
            )
        action_request = GrantRepositoryAccessRequest(
            idempotency_key=f"repository-access-{request.access_request_id}",
            case_id=snapshot.access_case.case_id,
            access_request_id=request.access_request_id,
            employee_id=snapshot.employee.employee_id,
            identity_id=snapshot.identity.identity_id,
            repository_id=snapshot.repository.repository_id,
            access_level=request.requested_level,
            reason=request.justification,
        )
        return {
            "decision": EmployeeWorkflowDecision.GRANT_ACCESS,
            "status": WorkflowStatus.ACTION_PENDING,
            "access_request": action_request,
            "node_history": ["decide"],
        }

    @staticmethod
    def _review(code: str, message: str) -> dict[str, object]:
        return {
            "decision": EmployeeWorkflowDecision.ESCALATE,
            "status": WorkflowStatus.ESCALATED,
            "error_code": code,
            "error_message": message,
            "node_history": ["decide"],
        }

    def _grant_access(self, state: EmployeeAccessWorkflowState) -> dict[str, object]:
        try:
            operation = self.action_tools.grant_repository_access(
                state["access_request"], state["actor"]
            )
        except OperationError as exc:
            return {
                "status": WorkflowStatus.ESCALATED,
                "error_code": exc.code,
                "error_message": exc.message,
                "node_history": ["grant_access"],
            }
        return {
            "status": WorkflowStatus.VERIFYING,
            "operation": operation,
            "node_history": ["grant_access"],
        }

    def _verify_access(self, state: EmployeeAccessWorkflowState) -> dict[str, object]:
        operation = state.get("operation")
        if operation is None:
            raise RuntimeError("verification reached without an operation")
        with self.session_factory() as session:
            snapshot = EmployeeITStore(session).get_snapshot(state["case_id"])
        access = snapshot.repository_access
        matches = bool(
            operation.status == OperationStatus.COMPLETED
            and operation.verified
            and access is not None
            and access.access_id == operation.resource_id
            and access.level == snapshot.access_request.requested_level
            and access.status == MembershipStatus.ACTIVE
            and snapshot.group_membership is not None
            and snapshot.group_membership.status == MembershipStatus.ACTIVE
            and snapshot.access_request.status == AccessRequestStatus.FULFILLED
            and snapshot.access_case.status == ITCaseStatus.RESOLVED
            and snapshot.ticket.status == ITTicketStatus.RESOLVED
            and any(item.status == ITNotificationStatus.SENT for item in snapshot.notifications)
        )
        if not matches:
            return {
                "status": WorkflowStatus.ESCALATED,
                "error_code": "workflow_verification_failed",
                "error_message": "Fresh IT state did not match the authorized action.",
                "node_history": ["verify_access"],
            }
        return {
            "snapshot": snapshot,
            "verified_access_id": access.access_id if access else None,
            "node_history": ["verify_access"],
        }

    @staticmethod
    def _complete(state: EmployeeAccessWorkflowState) -> dict[str, object]:
        access_id = state["verified_access_id"]
        return {
            "status": WorkflowStatus.COMPLETED,
            "outcome": EmployeeWorkflowOutcome.ACCESS_VERIFIED,
            "resolution_summary": (
                f"Repository access {access_id} was granted and independently verified."
            ),
            "node_history": ["complete"],
        }

    def _already_satisfied(self, state: EmployeeAccessWorkflowState) -> dict[str, object]:
        snapshot = state["snapshot"]
        access = snapshot.repository_access
        with self.session_factory.begin() as session:
            access_case = session.get(ITAccessCaseRecord, snapshot.access_case.case_id)
            request = session.get(ITAccessRequestRecord, snapshot.access_request.access_request_id)
            ticket = session.get(ITTicketRecord, snapshot.ticket.ticket_id)
            if access_case is not None and request is not None and ticket is not None:
                access_case.status = ITCaseStatus.RESOLVED
                access_case.updated_at = self.clock()
                request.status = AccessRequestStatus.FULFILLED
                ticket.status = ITTicketStatus.RESOLVED
                ticket.updated_at = self.clock()
        return {
            "status": WorkflowStatus.COMPLETED,
            "outcome": EmployeeWorkflowOutcome.ALREADY_SATISFIED,
            "verified_access_id": access.access_id if access else None,
            "resolution_summary": (
                "The requested repository access already exists; no duplicate action was taken."
            ),
            "node_history": ["already_satisfied"],
        }

    @staticmethod
    def _escalate(state: EmployeeAccessWorkflowState) -> dict[str, object]:
        message = state.get("error_message") or "The access case requires manual review."
        return {
            "status": WorkflowStatus.ESCALATED,
            "outcome": EmployeeWorkflowOutcome.NEEDS_REVIEW,
            "decision": EmployeeWorkflowDecision.ESCALATE,
            "error_code": state.get("error_code") or "manual_review_required",
            "error_message": message,
            "resolution_summary": f"No new access was granted. {message}",
            "node_history": ["escalate"],
        }

    def _result(self, state: EmployeeAccessWorkflowState) -> EmployeeAccessWorkflowResult:
        return EmployeeAccessWorkflowResult(
            workflow_id=state["workflow_id"],
            case_id=state["case_id"],
            status=state["status"],
            outcome=state["outcome"],
            decision=state["decision"],
            evidence=state["evidence"],
            policy_citations=state["policy_citations"],
            reasoning=state.get("reasoning"),
            agent_assessment=state.get("agent_assessment"),
            operation=state.get("operation"),
            verified_access_id=state.get("verified_access_id"),
            resolution_summary=state["resolution_summary"],
            error_code=state.get("error_code"),
            error_message=state.get("error_message"),
            node_history=state["node_history"],
            execution_mode=(
                "rules_only" if not state.get("agent_attempted") else self.model_execution_mode
            ),
        )
