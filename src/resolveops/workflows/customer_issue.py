import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any, Protocol, cast

from langchain_core.runnables import RunnableConfig, RunnableLambda
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, interrupt
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from resolveops.agents.budgets import AgentBudgetExceeded
from resolveops.agents.models import AgentDomain, MultiAgentReasoningResult
from resolveops.database.records import CaseIssueEvidenceRecord, CaseIssueRecord, RefundRecord
from resolveops.knowledge.embeddings import EmbeddingProvider
from resolveops.knowledge.retrieval import HybridPolicyRetriever
from resolveops.models.case import CaseIssueStatus, CaseIssueType, IssueFinding
from resolveops.models.refund import RefundStatus
from resolveops.observability.models import TraceComponent
from resolveops.observability.sinks import DEFAULT_TRACE_SINK, TraceSink
from resolveops.observability.tracing import Span, current_trace_id, observed_span, trace_context
from resolveops.operations.actions import ActionTools
from resolveops.operations.auth import (
    has_approval_path,
    require_permission,
    require_refund_limit,
)
from resolveops.operations.errors import (
    ApprovalRequiredError,
    AuthorizationError,
    OperationError,
    RecoveryRequiredError,
    ResourceNotFoundError,
    VerificationError,
)
from resolveops.operations.models import (
    Actor,
    ActorRole,
    OperationStatus,
    Permission,
)
from resolveops.operations.proposals import investigate_issue, same_refund_target
from resolveops.operations.reads import OperationsReadTools
from resolveops.reasoning.agent import CaseReasoner
from resolveops.reasoning.errors import ReasoningError, ReasoningProviderError
from resolveops.reasoning.models import ReasoningDisposition, ReasoningPolicyExcerpt
from resolveops.reasoning.providers import ReasoningProvider
from resolveops.responses.customer import CustomerResponseComposer
from resolveops.workflows.case_state import refresh_refund_result, synchronize_case_state
from resolveops.workflows.lifecycle import WorkflowLifecycleStore
from resolveops.workflows.models import (
    ApprovalStatus,
    PolicyCitation,
    WorkflowApproval,
    WorkflowApprovalDecision,
    WorkflowDecision,
    WorkflowEventType,
    WorkflowOutcome,
    WorkflowPause,
    WorkflowRequest,
    WorkflowResult,
    WorkflowStatus,
)
from resolveops.workflows.state import WorkflowState
from resolveops.workflows.timeline import node_timeline_events

ACTIVE_REFUND_STATUSES = {
    RefundStatus.PENDING,
    RefundStatus.PROCESSING,
    RefundStatus.COMPLETED,
}

LOGGER = logging.getLogger(__name__)

POLICY_QUERY = {
    CaseIssueType.DUPLICATE_CHARGE: (
        "distinct captured payments same order amount currency existing refund "
        "authorization and verification"
    ),
    CaseIssueType.MISSING_RETURN_REFUND: (
        "received return item paid amount existing return refund status verification"
    ),
}

REQUIRED_POLICY = {
    CaseIssueType.DUPLICATE_CHARGE: "POLICY-DUPLICATE-CHARGE",
    CaseIssueType.MISSING_RETURN_REFUND: "POLICY-RETURN-REFUND",
}


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


class CustomerIssueWorkflow:
    """Case workflow with bounded LLM advice and deterministic control gates."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        embedding_provider: EmbeddingProvider,
        *,
        action_tools: ActionTools | None = None,
        reasoning_provider: ReasoningProvider | None = None,
        agent_runtime: IntegratedAgentRuntime | None = None,
        tenant_id: str = "TENANT-LOCAL",
        model_execution_mode: str = "unverified_model",
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        lifecycle_store: WorkflowLifecycleStore | None = None,
        observability_sink: TraceSink | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if (checkpointer is None) != (lifecycle_store is None):
            raise ValueError("checkpointer and lifecycle_store must be configured together")
        self.session_factory = session_factory
        self.embedding_provider = embedding_provider
        self.clock = clock or (lambda: datetime.now(UTC))
        self.action_tools = action_tools or ActionTools(session_factory, clock=self.clock)
        self.observability_sink = observability_sink or DEFAULT_TRACE_SINK
        self.agent_runtime = agent_runtime
        self.tenant_id = tenant_id
        self.model_execution_mode = model_execution_mode
        self.reasoner = (
            CaseReasoner(
                reasoning_provider,
                observability_sink=self.observability_sink,
                clock=self.clock,
            )
            if reasoning_provider
            else None
        )
        self.checkpointer = checkpointer
        self.lifecycle_store = lifecycle_store
        self.response_composer = CustomerResponseComposer()
        self.graph = self._build_graph()

    def run(self, request: WorkflowRequest) -> WorkflowResult:
        if self.checkpointer is not None:
            raise RuntimeError("use start() for a durable workflow")
        with (
            trace_context(
                self.observability_sink,
                workflow_id=request.workflow_id,
                case_id=request.case_id,
            ),
            observed_span(TraceComponent.WORKFLOW, "run") as span,
        ):
            final = cast(WorkflowState, self.graph.invoke(self._initial_state(request)))
            result = self._result_from_state(final)
            synchronize_case_state(self.session_factory, result, self.clock)
            span.set_attribute("outcome", result.outcome.value)
            span.set_attribute("final_status", result.status.value)
            return result

    def start(self, request: WorkflowRequest) -> WorkflowResult | WorkflowPause:
        with (
            trace_context(
                self.observability_sink,
                workflow_id=request.workflow_id,
                case_id=request.case_id,
            ),
            observed_span(TraceComponent.WORKFLOW, "start") as span,
        ):
            lifecycle = self._required_lifecycle()
            lifecycle.start(request)
            config = self._config(request.workflow_id)
            snapshot = self.graph.get_state(config)
            if snapshot.values:
                result = self._execution_from_snapshot(config)
            else:
                self.graph.invoke(
                    self._initial_state(request),
                    config,
                    durability="sync",
                )
                result = self._execution_from_snapshot(config)
            self._set_execution_attributes(span, result)
            return result

    def resume(self, decision: WorkflowApprovalDecision) -> WorkflowResult | WorkflowPause:
        lifecycle = self._required_lifecycle()
        approval = lifecycle.get_approval(decision.approval_id)
        with (
            trace_context(
                self.observability_sink,
                workflow_id=approval.workflow_id,
                case_id=approval.case_id,
            ),
            observed_span(TraceComponent.WORKFLOW, "resume") as span,
        ):
            config = self._config(approval.workflow_id)
            snapshot = self.graph.get_state(config)
            if not snapshot.interrupts:
                if approval.status != ApprovalStatus.PENDING:
                    lifecycle.decide_approval(decision)
                result = self._execution_from_snapshot(config)
            else:
                self.graph.invoke(
                    Command(resume=decision.model_dump(mode="json")),
                    config,
                    durability="sync",
                )
                result = self._execution_from_snapshot(config)
            self._set_execution_attributes(span, result)
            return result

    def get_execution(self, workflow_id: str) -> WorkflowResult | WorkflowPause:
        self._required_lifecycle().get_run(workflow_id)
        return self._execution_from_snapshot(self._config(workflow_id))

    @staticmethod
    def _initial_state(request: WorkflowRequest) -> WorkflowState:
        return {
            "workflow_id": request.workflow_id,
            "case_id": request.case_id,
            "issue_id": request.issue_id,
            "actor": request.actor,
            "refund_request": request.refund_request,
            "investigation_only": request.investigation_only,
            "status": WorkflowStatus.RECEIVED,
            "evidence": [],
            "policy_citations": [],
            "policy_excerpts": [],
            "node_history": [],
            "approval": None,
            "agent_assessment": None,
        }

    def _result_from_state(self, final: WorkflowState) -> WorkflowResult:
        final_response = self.response_composer.compose(
            status=final["status"],
            outcome=final["outcome"],
            issue_id=final["issue_id"],
            verified_resource_id=final.get("verified_resource_id"),
            existing_refund_id=final.get("existing_refund_id"),
            error_code=final.get("error_code"),
            policy_citations=final["policy_citations"],
            generated_at=self.clock(),
        )
        result = WorkflowResult(
            workflow_id=final["workflow_id"],
            case_id=final["case_id"],
            issue_id=final["issue_id"],
            status=final["status"],
            outcome=final["outcome"],
            issue_type=final["issue_type"],
            finding=final["finding"],
            decision=final["decision"],
            evidence=final["evidence"],
            policy_citations=final["policy_citations"],
            reasoning=final.get("reasoning"),
            agent_assessment=final.get("agent_assessment"),
            operation=final.get("operation"),
            verified_resource_id=final.get("verified_resource_id"),
            resolution_summary=final["resolution_summary"],
            final_response=final_response,
            error_code=final.get("error_code"),
            error_message=final.get("error_message"),
            node_history=final["node_history"],
            execution_mode=self.model_execution_mode
            if final.get("agent_attempted")
            else "rules_only",
        )
        result = refresh_refund_result(self.session_factory, result, self.clock)
        self._record_event_once(
            final["workflow_id"],
            WorkflowEventType.FINAL_RESPONSE_CREATED,
            details={
                "outcome": result.outcome.value,
                "verified_fact_count": len(result.final_response.verified_fact_ids),
                "policy_citation_count": len(result.final_response.policy_citation_ids),
            },
        )
        return result

    def _execution_from_snapshot(self, config: RunnableConfig) -> WorkflowResult | WorkflowPause:
        lifecycle = self._required_lifecycle()
        snapshot = self.graph.get_state(config)
        if snapshot.interrupts:
            raw = snapshot.interrupts[0].value
            values = cast(WorkflowState, snapshot.values)
            approval = (
                raw if isinstance(raw, WorkflowApproval) else WorkflowApproval.model_validate(raw)
            )
            pause = WorkflowPause(
                workflow_id=approval.workflow_id,
                case_id=approval.case_id,
                issue_id=approval.issue_id,
                approval=approval,
                agent_assessment=values.get("agent_assessment"),
                execution_mode=self.model_execution_mode
                if values.get("agent_attempted")
                else "rules_only",
            )
            synchronize_case_state(self.session_factory, pause, self.clock)
            return pause
        if snapshot.next:
            raise RuntimeError("durable workflow stopped before reaching a stable state")
        if not snapshot.values:
            raise RuntimeError("durable workflow has no checkpointed state")
        result = self._result_from_state(cast(WorkflowState, snapshot.values))
        lifecycle.finish(result)
        synchronize_case_state(self.session_factory, result, self.clock)
        return result

    def _required_lifecycle(self) -> WorkflowLifecycleStore:
        if self.lifecycle_store is None or self.checkpointer is None:
            raise RuntimeError("durable workflow services are not configured")
        return self.lifecycle_store

    @staticmethod
    def _config(workflow_id: str) -> RunnableConfig:
        return {"configurable": {"thread_id": workflow_id}}

    def _build_graph(
        self,
    ) -> CompiledStateGraph[WorkflowState, None, WorkflowState, WorkflowState]:
        builder = StateGraph(WorkflowState)
        builder.add_node("load_case", self._observed_node("load_case", self._load_case))
        builder.add_node(
            "investigate_duplicate",
            self._observed_node("investigate_duplicate", self._investigate_duplicate),
        )
        builder.add_node(
            "investigate_return",
            self._observed_node("investigate_return", self._investigate_return),
        )
        builder.add_node(
            "retrieve_policy", self._observed_node("retrieve_policy", self._retrieve_policy)
        )
        builder.add_node("reason_case", self._observed_node("reason_case", self._reason_case))
        builder.add_node("decide", self._observed_node("decide", self._decide))
        builder.add_node("approval_gate", self._observed_node("approval_gate", self._approval_gate))
        builder.add_node(
            "execute_refund", self._observed_node("execute_refund", self._execute_refund)
        )
        builder.add_node("verify_action", self._observed_node("verify_action", self._verify_action))
        builder.add_node("complete", self._observed_node("complete", self._complete))
        builder.add_node("no_action", self._observed_node("no_action", self._no_action))
        builder.add_node("wait_external", self._observed_node("wait_external", self._wait_external))
        builder.add_node("escalate", self._observed_node("escalate", self._escalate))

        builder.add_edge(START, "load_case")
        builder.add_conditional_edges(
            "load_case",
            self._route_issue,
            {
                CaseIssueType.DUPLICATE_CHARGE.value: "investigate_duplicate",
                CaseIssueType.MISSING_RETURN_REFUND.value: "investigate_return",
            },
        )
        builder.add_edge("investigate_duplicate", "retrieve_policy")
        builder.add_edge("investigate_return", "retrieve_policy")
        builder.add_edge("retrieve_policy", "reason_case")
        builder.add_conditional_edges(
            "reason_case",
            self._route_reasoning,
            {"decide": "decide", "escalate": "escalate"},
        )
        builder.add_conditional_edges(
            "decide",
            self._route_decision,
            {
                WorkflowDecision.EXECUTE_REFUND.value: "approval_gate",
                WorkflowDecision.MONITOR_EXISTING_REFUND.value: "wait_external",
                WorkflowDecision.ESCALATE.value: "escalate",
                WorkflowDecision.NO_ACTION.value: "no_action",
            },
        )
        builder.add_conditional_edges(
            "approval_gate",
            self._route_approval,
            {"execute": "execute_refund", "escalate": "escalate"},
        )
        builder.add_conditional_edges(
            "execute_refund",
            self._route_execution,
            {
                "verify": "verify_action",
                "wait": "wait_external",
                "escalate": "escalate",
            },
        )
        builder.add_conditional_edges(
            "verify_action",
            self._route_verification,
            {"complete": "complete", "escalate": "escalate"},
        )
        builder.add_edge("complete", END)
        builder.add_edge("no_action", END)
        builder.add_edge("wait_external", END)
        builder.add_edge("escalate", END)
        return builder.compile(
            checkpointer=self.checkpointer,
            name="resolveops-customer-issue",
        )

    def _observed_node(
        self,
        name: str,
        node: Callable[[WorkflowState], dict[str, object]],
    ) -> RunnableLambda[WorkflowState, dict[str, object]]:
        def invoke(state: WorkflowState) -> dict[str, object]:
            with observed_span(
                TraceComponent.WORKFLOW_NODE,
                name,
                sink=self.observability_sink,
            ) as span:
                result = node(state)
                self._record_node_events(name, state, result)
                status_value = result.get("status")
                if isinstance(status_value, WorkflowStatus):
                    span.set_attribute("status", status_value.value)
                return result

        return RunnableLambda(invoke, name=name)

    def _record_node_events(
        self,
        name: str,
        state: WorkflowState,
        result: dict[str, object],
    ) -> None:
        for event in node_timeline_events(name, state, result):
            self._record_event_once(
                state["workflow_id"],
                event.event_type,
                actor_id=event.actor_id,
                actor_role=event.actor_role,
                details=event.details,
            )

    def _record_event_once(
        self,
        workflow_id: str,
        event_type: WorkflowEventType,
        *,
        actor_id: str | None = None,
        actor_role: ActorRole | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        if self.lifecycle_store is None:
            return
        self.lifecycle_store.record_event_once(
            workflow_id,
            event_type,
            actor_id=actor_id,
            actor_role=actor_role,
            details=details,
        )

    @staticmethod
    def _set_execution_attributes(span: Span, result: WorkflowResult | WorkflowPause) -> None:
        if isinstance(result, WorkflowResult):
            span.set_attribute("outcome", result.outcome.value)
            span.set_attribute("final_status", result.status.value)
        else:
            span.set_attribute("outcome", "paused")

    def _load_case(self, state: WorkflowState) -> dict[str, object]:
        with self.session_factory() as session:
            customer_case = OperationsReadTools(session, state["actor"]).get_case(state["case_id"])
        issue = next(
            (item for item in customer_case.issues if item.issue_id == state["issue_id"]),
            None,
        )
        if issue is None:
            raise ResourceNotFoundError(
                "resource_not_found",
                f"issue {state['issue_id']} does not exist in case {state['case_id']}",
            )
        return {
            "status": WorkflowStatus.INVESTIGATING,
            "issue_type": issue.issue_type,
            "issue_status": issue.status.value,
            "finding": issue.finding,
            "order_id": issue.order_id,
            "customer_id": customer_case.customer_id,
            "complaint_text": customer_case.complaint_text,
            "case_issue_count": len(customer_case.issues),
            "payment_ids": list(issue.payment_ids),
            "return_id": issue.return_id,
            "evidence": [item.summary for item in issue.evidence],
            "node_history": ["load_case"],
        }

    @staticmethod
    def _route_issue(state: WorkflowState) -> str:
        return state["issue_type"].value

    def _investigate_duplicate(self, state: WorkflowState) -> dict[str, object]:
        return self._investigate(state, "investigate_duplicate")

    def _investigate_return(self, state: WorkflowState) -> dict[str, object]:
        return self._investigate(state, "investigate_return")

    def _investigate(self, state: WorkflowState, node: str) -> dict[str, object]:
        with self.session_factory.begin() as session:
            result = investigate_issue(session, state["case_id"], state["issue_id"])
            issue = session.get(CaseIssueRecord, state["issue_id"])
            if issue is None:
                raise ValueError("investigated issue disappeared")
            issue.finding = result.finding
            if result.proposal:
                issue.status = CaseIssueStatus.ACTION_PENDING
            for index, (source, reference_id, summary) in enumerate(result.evidence):
                evidence_id = (
                    "EVD-" + sha256(f"{state['workflow_id']}|{index}".encode()).hexdigest()[:40]
                )
                if session.get(CaseIssueEvidenceRecord, evidence_id) is None:
                    session.add(
                        CaseIssueEvidenceRecord(
                            evidence_id=evidence_id,
                            issue_id=issue.issue_id,
                            source=source,
                            reference_id=reference_id,
                            summary=summary,
                            collected_at=self.clock(),
                        )
                    )
            proposal = result.proposal
            supplied = state.get("refund_request")
            error = result.error
            if (
                supplied is not None
                and proposal is not None
                and not same_refund_target(supplied, proposal)
            ):
                error = "The supplied action conflicts with the independently verified refund candidate."
                proposal = None
            # Internal callers may supply a retry key, but public investigation never supplies a candidate.
            if supplied is not None and proposal is not None:
                proposal = proposal.model_copy(update={"idempotency_key": supplied.idempotency_key})
            return {
                "finding": result.finding,
                "issue_status": issue.status.value,
                "refund_request": proposal,
                "existing_refund_id": result.existing_refund_id,
                "evidence": [text for _, _, text in result.evidence],
                "investigation_error": error,
                "node_history": [node],
            }

    def _retrieve_policy(self, state: WorkflowState) -> dict[str, object]:
        # Durable JSON checkpoints restore enum values as strings.
        issue_type = CaseIssueType(state["issue_type"])
        with self.session_factory() as session:
            results = HybridPolicyRetriever(session, self.embedding_provider).search(
                POLICY_QUERY[issue_type],
                as_of=self.clock(),
                issue_type=issue_type,
                top_k=3,
            )
        citations = [
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
        ]
        excerpts = [
            ReasoningPolicyExcerpt(
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                version=item.document_version,
                section=item.heading,
                text=item.text,
            )
            for item in results
        ]
        return {
            "status": WorkflowStatus.POLICY_REVIEW,
            "policy_citations": citations,
            "policy_excerpts": excerpts,
            "node_history": ["retrieve_policy"],
        }

    def _reason_case(self, state: WorkflowState) -> dict[str, object]:
        if self.agent_runtime is not None and self._requires_multi_agent(state):
            try:
                assessment = self.agent_runtime.run(
                    workflow_id=state["workflow_id"],
                    case_id=state["case_id"],
                    tenant_id=self.tenant_id,
                    domain=AgentDomain.CUSTOMER_OPERATIONS,
                    objective=(
                        state.get("complaint_text")
                        or f"Investigate {CaseIssueType(state['issue_type']).value} using trusted evidence."
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
                    "Integrated agent assessment stopped for workflow %s (%s): %s",
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
                        "The specialist assessment stopped safely before deterministic action "
                        f"controls: {type(exc).__name__}."
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
                        "The independent critic did not clear the recommendation for the "
                        "deterministic control plane."
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
                issue_id=state["issue_id"],
                issue_type=state["issue_type"],
                persisted_finding=state["finding"].value,
                persisted_status=state["issue_status"],
                existing_refund_id=state.get("existing_refund_id"),
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

    @staticmethod
    def _requires_multi_agent(state: WorkflowState) -> bool:
        """Route complex cases through specialists without granting them action authority."""
        return state.get("case_issue_count", 1) > 1 or bool(state.get("investigation_error"))

    @staticmethod
    def _route_reasoning(state: WorkflowState) -> str:
        return "escalate" if state["status"] == WorkflowStatus.ESCALATED else "decide"

    def _decide(self, state: WorkflowState) -> dict[str, object]:
        expected_policy = REQUIRED_POLICY[state["issue_type"]]
        if not any(
            citation.document_id == expected_policy for citation in state["policy_citations"]
        ):
            return self._review_decision(
                "required_policy_not_found",
                f"Active policy {expected_policy} was not retrieved for the issue.",
            )
        assessment = state.get("agent_assessment")
        if assessment is not None:
            if assessment.resolution is None:
                return self._review_decision(
                    "agent_proposal_requires_review",
                    "The investigation stopped before a supported resolution was available.",
                )
            recommendation = next(
                (
                    item
                    for item in assessment.resolution.issue_resolutions
                    if item.issue_id == state["issue_id"]
                ),
                None,
            )
            if (
                assessment.case_id != state["case_id"]
                or assessment.tenant_id != self.tenant_id
                or assessment.resolution.escalation_needed
                or assessment.resolution.uncertainty
                or recommendation is None
            ):
                return self._review_decision(
                    "agent_proposal_requires_review",
                    "The specialist recommendation is incomplete, uncertain or requires review.",
                )
            if recommendation.disposition in {"escalate", "request_information"}:
                return self._review_decision(
                    "agent_requires_information",
                    recommendation.clarification_question or recommendation.recommendation,
                )
            candidate = state.get("refund_request")
            if recommendation.disposition == "refund":
                proposed = [
                    a
                    for a in assessment.resolution.proposed_actions
                    if a.issue_id == state["issue_id"]
                ]
                try:
                    supported = (
                        candidate is not None
                        and len(proposed) == 1
                        and proposed[0].action_type in {"issue_refund", "refund"}
                        and proposed[0].resource_id == candidate.payment_id
                        and Decimal(proposed[0].amount or "NaN") == candidate.amount
                    )
                except InvalidOperation:
                    supported = False
                if not supported:
                    return self._review_decision(
                        "agent_action_mismatch",
                        "The agent action does not match the authoritative payment and amount.",
                    )
            elif recommendation.disposition == "wait" and not state.get("existing_refund_id"):
                return self._review_decision(
                    "agent_wait_requires_review", recommendation.recommendation
                )
            elif (
                recommendation.disposition == "no_action"
                and state["finding"] != IssueFinding.REJECTED
            ):
                return self._review_decision(
                    "agent_no_action_requires_review", recommendation.recommendation
                )
        if state.get("existing_refund_id") is not None:
            return {
                "decision": WorkflowDecision.MONITOR_EXISTING_REFUND,
                "status": WorkflowStatus.WAITING_EXTERNAL,
                "node_history": ["decide"],
            }
        if state.get("investigation_error"):
            return self._review_decision(
                "evidence_review_required",
                state["investigation_error"] or "Evidence review required.",
            )
        if state["finding"] == IssueFinding.REJECTED:
            return {"decision": WorkflowDecision.NO_ACTION, "node_history": ["decide"]}
        if (
            state["finding"] != IssueFinding.CONFIRMED
            or state["issue_status"] != CaseIssueStatus.ACTION_PENDING.value
        ):
            return self._review_decision(
                "investigation_not_confirmed",
                "The persisted issue finding and lifecycle state do not authorize an action.",
            )
        if state["refund_request"] is None:
            return self._review_decision(
                "refund_request_missing",
                "A confirmed issue requires a typed refund proposal before execution.",
            )
        reasoning = state.get("reasoning")
        if reasoning is not None and (
            reasoning.assessment.recommended_disposition != ReasoningDisposition.REFUND_CANDIDATE
        ):
            return self._review_decision(
                "reasoning_recommends_review",
                "The advisory reasoning assessment did not support a refund candidate; "
                "deterministic execution was stopped for review.",
            )
        return {
            "decision": WorkflowDecision.EXECUTE_REFUND,
            "status": WorkflowStatus.ACTION_PENDING,
            "proposal_fingerprint": self._proposal_fingerprint(state),
            "node_history": ["decide"],
        }

    @staticmethod
    def _review_decision(code: str, message: str) -> dict[str, object]:
        return {
            "decision": WorkflowDecision.ESCALATE,
            "status": WorkflowStatus.ESCALATED,
            "error_code": code,
            "error_message": message,
            "node_history": ["decide"],
        }

    @staticmethod
    def _route_decision(state: WorkflowState) -> str:
        return state["decision"].value

    def _approval_gate(self, state: WorkflowState) -> dict[str, object]:
        if self.lifecycle_store is None:
            return {"node_history": ["approval_gate"]}
        request = state["refund_request"]
        if request is None:
            raise RuntimeError("approval gate reached without a refund request")
        try:
            require_permission(state["actor"], Permission.ISSUE_REFUND)
        except AuthorizationError as exc:
            return self._approval_error(exc.code, exc.message)
        try:
            require_refund_limit(state["actor"], request.amount, request.currency)
            if not state.get("investigation_only"):
                return {"node_history": ["approval_gate"]}
            approval_reason = (
                "Investigation finished. Review this proposal before any refund is submitted."
            )
        except ApprovalRequiredError as exc:
            if not has_approval_path(request.amount, request.currency):
                return self._approval_error(
                    "approval_path_unavailable",
                    "No configured approval role can authorize this refund amount and currency.",
                )
            approval_reason = exc.message

        approval = self.lifecycle_store.request_refund_approval(
            workflow_id=state["workflow_id"],
            request=request,
            requested_by=state["actor"].actor_id,
            requested_role=state["actor"].role,
            reason=approval_reason,
        )
        if self.clock() - approval.requested_at > timedelta(minutes=30):
            return self._approval_error(
                "approval_expired", "This proposal expired. Investigate current evidence again."
            )

        approval = self._resolve_pending_approval(approval)

        if approval.status == ApprovalStatus.REJECTED:
            return {
                "approval": approval,
                "status": WorkflowStatus.ESCALATED,
                "error_code": "approval_rejected",
                "error_message": (
                    f"Refund approval {approval.approval_id} was rejected by {approval.decided_by}."
                ),
                "node_history": ["approval_gate"],
            }
        if approval.status != ApprovalStatus.APPROVED:
            raise RuntimeError("approval gate resumed without a final decision")
        if approval.decided_by is None or approval.decided_role is None:
            raise RuntimeError("approved decision is missing its actor")
        if state.get("proposal_fingerprint") != self._proposal_fingerprint(state):
            return self._approval_error(
                "approval_evidence_changed",
                "Evidence or policy changed after investigation; create a fresh proposal.",
            )
        return {
            "actor": Actor(
                actor_id=approval.decided_by,
                role=approval.decided_role,
            ),
            "approval": approval,
            "status": WorkflowStatus.ACTION_PENDING,
            "node_history": ["approval_gate"],
        }

    def _resolve_pending_approval(self, approval: WorkflowApproval) -> WorkflowApproval:
        if approval.status != ApprovalStatus.PENDING:
            return approval
        raw_decision = interrupt(
            approval.model_dump(mode="json"),
            response_schema=WorkflowApprovalDecision,
        )
        decision = (
            raw_decision
            if isinstance(raw_decision, WorkflowApprovalDecision)
            else WorkflowApprovalDecision.model_validate(raw_decision)
        )
        if decision.approval_id != approval.approval_id:
            raise ValueError("resume decision targets a different approval")
        if self.lifecycle_store is None:
            raise RuntimeError("pending approval requires a lifecycle store")
        return self.lifecycle_store.decide_approval(decision)

    @staticmethod
    def _approval_error(code: str, message: str) -> dict[str, object]:
        return {
            "status": WorkflowStatus.ESCALATED,
            "error_code": code,
            "error_message": message,
            "node_history": ["approval_gate"],
        }

    @staticmethod
    def _route_approval(state: WorkflowState) -> str:
        return "escalate" if state["status"] == WorkflowStatus.ESCALATED else "execute"

    def _execute_refund(self, state: WorkflowState) -> dict[str, object]:
        request = state["refund_request"]
        if request is None:
            raise RuntimeError("execute_refund reached without a refund request")
        try:
            operation = self.action_tools.issue_refund(request, state["actor"])
        except OperationError as exc:
            if isinstance(exc, (VerificationError, RecoveryRequiredError)):
                with self.session_factory() as session:
                    existing = self._active_issue_refund(session, state["issue_id"])
                if existing is not None:
                    return {
                        "decision": WorkflowDecision.MONITOR_EXISTING_REFUND,
                        "status": WorkflowStatus.WAITING_EXTERNAL,
                        "existing_refund_id": existing.refund_id,
                        "error_code": None,
                        "error_message": None,
                        "node_history": [
                            "execute_refund",
                            "replan_after_partial_failure",
                        ],
                    }
            return {
                "status": WorkflowStatus.ESCALATED,
                "error_code": exc.code,
                "error_message": exc.message,
                "node_history": ["execute_refund"],
            }
        return {
            "status": WorkflowStatus.VERIFYING,
            "operation": operation,
            "node_history": ["execute_refund"],
        }

    @staticmethod
    def _route_execution(state: WorkflowState) -> str:
        if state["status"] == WorkflowStatus.WAITING_EXTERNAL:
            return "wait"
        return "verify" if state.get("operation") is not None else "escalate"

    def _verify_action(self, state: WorkflowState) -> dict[str, object]:
        operation = state.get("operation")
        request = state["refund_request"]
        if operation is None or request is None:
            raise RuntimeError("verification reached without an operation and request")
        try:
            with self.session_factory() as session:
                refund = OperationsReadTools(session, state["actor"]).get_refund(
                    operation.resource_id
                )
        except ResourceNotFoundError as exc:
            return {
                "status": WorkflowStatus.ESCALATED,
                "error_code": "workflow_verification_failed",
                "error_message": exc.message,
                "node_history": ["verify_action"],
            }
        matches = (
            operation.status == OperationStatus.COMPLETED
            and operation.verified
            and refund.issue_id == state["issue_id"]
            and refund.payment_id == request.payment_id
            and refund.amount == request.amount
            and refund.currency == request.currency
            and refund.kind == request.kind
            and refund.return_id == request.return_id
            and refund.status in ACTIVE_REFUND_STATUSES
        )
        if not matches:
            return {
                "status": WorkflowStatus.ESCALATED,
                "error_code": "workflow_verification_failed",
                "error_message": "Fresh refund state did not match the authorized action.",
                "node_history": ["verify_action"],
            }
        return {
            "verified_resource_id": refund.refund_id,
            "observed_refund_status": refund.status.value,
            "node_history": ["verify_action"],
        }

    @staticmethod
    def _route_verification(state: WorkflowState) -> str:
        return "complete" if state.get("verified_resource_id") is not None else "escalate"

    @staticmethod
    def _complete(state: WorkflowState) -> dict[str, object]:
        resource_id = state["verified_resource_id"]
        return {
            "status": WorkflowStatus.WAITING_EXTERNAL,
            "outcome": WorkflowOutcome.REFUND_SUBMITTED,
            "resolution_summary": (
                f"Refund {resource_id} was created and independently verified. The case remains "
                "open until the external refund reaches its final state."
            ),
            "node_history": ["complete"],
        }

    @staticmethod
    def _no_action(state: WorkflowState) -> dict[str, object]:
        return {
            "status": WorkflowStatus.COMPLETED,
            "outcome": WorkflowOutcome.NO_ACTION_REQUIRED,
            "resolution_summary": "Current captured payments do not establish duplicate collection. No refund was submitted.",
            "node_history": ["no_action"],
        }

    def _proposal_fingerprint(self, state: WorkflowState) -> str:
        with self.session_factory() as session:
            result = investigate_issue(session, state["case_id"], state["issue_id"])
        current_policy = self._retrieve_policy(state)["policy_citations"]
        value = repr(
            (
                result.finding,
                result.evidence,
                result.proposal.model_dump(mode="json") if result.proposal else None,
                result.existing_refund_id,
                current_policy,
            )
        )
        return sha256(value.encode()).hexdigest()

    @staticmethod
    def _wait_external(state: WorkflowState) -> dict[str, object]:
        refund_id = state["existing_refund_id"]
        return {
            "verified_resource_id": refund_id,
            "status": WorkflowStatus.WAITING_EXTERNAL,
            "outcome": WorkflowOutcome.WAITING_EXTERNAL,
            "resolution_summary": (
                f"Refund {refund_id} already exists. No duplicate action was taken; wait for its "
                "external status to become final."
            ),
            "node_history": ["wait_external"],
        }

    @staticmethod
    def _escalate(state: WorkflowState) -> dict[str, object]:
        message = state.get("error_message") or "The workflow requires manual review."
        return {
            "status": WorkflowStatus.ESCALATED,
            "outcome": WorkflowOutcome.NEEDS_REVIEW,
            "decision": WorkflowDecision.ESCALATE,
            "error_code": state.get("error_code") or "manual_review_required",
            "error_message": message,
            "resolution_summary": f"No new action was completed. {message}",
            "node_history": ["escalate"],
        }

    @staticmethod
    def _active_issue_refund(session: Session, issue_id: str) -> RefundRecord | None:
        return session.scalar(
            select(RefundRecord)
            .where(
                RefundRecord.issue_id == issue_id,
                RefundRecord.status.in_(ACTIVE_REFUND_STATUSES),
            )
            .order_by(RefundRecord.created_at.desc(), RefundRecord.refund_id.desc())
        )
