from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import TypeVar, cast

from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from resolveops.agents.budgets import BudgetLedger
from resolveops.agents.invocation import AgentInvoker
from resolveops.agents.models import (
    AgentBudget,
    AgentRole,
    CriticDecision,
    CriticReport,
    EvidenceFact,
    InvestigationTurn,
    IssueResolution,
    PlanStep,
    PolicyTurn,
    ResolutionProposal,
    SupervisorPlan,
    ToolArguments,
    ToolRequest,
)
from resolveops.agents.persistence import AgentRunStore
from resolveops.agents.runtime import MultiAgentReasoningRuntime
from resolveops.agents.tools import AgentToolResult
from resolveops.database.base import Base
from resolveops.evaluation.agent_trajectory import (
    AgentTrajectoryCase,
    AgentTrajectoryObservation,
)
from resolveops.memory.store import ReviewedResolutionMemoryStore
from resolveops.orchestration.graph import HierarchicalAgentOrchestrator

OutputT = TypeVar("OutputT", bound=BaseModel)
NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)


class OfflineTrajectoryProvider:
    """Deterministic provider double for orchestration-contract evaluation only."""

    provider_name = "offline-contract"
    model_name = "deterministic-trajectory-v1"
    last_usage = None

    def __init__(self, case: AgentTrajectoryCase) -> None:
        self.case = case
        self.investigation_calls = 0
        self.policy_calls = 0
        self.critic_calls = 0

    def invoke(
        self,
        *,
        instructions: str,
        context: BaseModel | dict[str, object],
        response_model: type[OutputT],
    ) -> OutputT:
        if response_model is SupervisorPlan:
            value: BaseModel = SupervisorPlan(
                goal="Produce a supported advisory resolution.",
                issues=["one synthetic contract issue"],
                plan_steps=[
                    PlanStep(
                        step_id="investigate",
                        objective="Read current operational evidence.",
                        assigned_role=AgentRole.INVESTIGATION,
                    ),
                    PlanStep(
                        step_id="policy",
                        objective="Retrieve active policy evidence.",
                        assigned_role=AgentRole.POLICY,
                    ),
                ],
                required_evidence=["current resource state", "active policy"],
                delegations=[
                    AgentRole.INVESTIGATION,
                    AgentRole.POLICY,
                    AgentRole.RESOLUTION,
                    AgentRole.CRITIC,
                ],
                parallelizable_tasks=[],
                missing_information=["current resource state"],
                next_agent=AgentRole.INVESTIGATION,
                stopping_condition="Independent critic accepts or escalates.",
            )
        elif response_model is InvestigationTurn:
            self.investigation_calls += 1
            if self.investigation_calls % 2 == 1:
                tool_name = (
                    "get_case"
                    if self.case.domain.value == "customer_operations"
                    else "get_it_snapshot"
                )
                value = InvestigationTurn(
                    confidence=0.2,
                    missing_evidence=["current resource state"],
                    recommended_next_investigation="Read the current resource.",
                    next_tool=ToolRequest(
                        tool_name=tool_name,
                        arguments=ToolArguments(resource_id=self.case.evaluation_id),
                        purpose="Read scoped synthetic evidence.",
                    ),
                    complete=False,
                )
            else:
                value = InvestigationTurn(
                    facts=[
                        EvidenceFact(
                            evidence_id=f"E-{self.case.evaluation_id}",
                            fact="The current synthetic record supports bounded review.",
                            source=f"offline://{self.case.evaluation_id}",
                            observed_at=NOW,
                        )
                    ],
                    evidence_ids=[f"E-{self.case.evaluation_id}"],
                    confidence=0.9,
                    source_provenance=[f"offline://{self.case.evaluation_id}"],
                    complete=True,
                )
        elif response_model is PolicyTurn:
            self.policy_calls += 1
            if self.policy_calls % 2 == 1:
                value = PolicyTurn(
                    policy_interpretation="Policy evidence is still required.",
                    next_query="active synthetic resolution policy",
                    complete=False,
                )
            else:
                value = PolicyTurn(
                    applicable_policy="The active policy permits an advisory proposal after review.",
                    citations=["CHUNK-OFFLINE-1"],
                    policy_versions={"POLICY-OFFLINE": 1},
                    supporting_sections=["Review requirements"],
                    policy_interpretation="Current policy supports review, not autonomous execution.",
                    complete=True,
                )
        elif response_model is ResolutionProposal:
            value = ResolutionProposal(
                issue_resolutions=[
                    IssueResolution(
                        issue_id=f"ISSUE-{self.case.evaluation_id}",
                        recommendation="Prepare a bounded proposal for deterministic controls.",
                        evidence_ids=[f"E-{self.case.evaluation_id}"],
                        policy_citations=["CHUNK-OFFLINE-1"],
                    )
                ],
                evidence_support=[f"E-{self.case.evaluation_id}"],
                policy_support=["CHUNK-OFFLINE-1"],
                escalation_needed=self.case.scenario == "escalate",
            )
        elif response_model is CriticReport:
            self.critic_calls += 1
            if self.case.scenario == "revise_once" and self.critic_calls == 1:
                value = CriticReport(
                    decision=CriticDecision.REVISE,
                    missing_evidence=["one additional bounded review pass"],
                    summary="Revise once before control-plane handoff.",
                )
            elif self.case.scenario == "escalate":
                value = CriticReport(
                    decision=CriticDecision.ESCALATE,
                    missing_evidence=["human judgment is required"],
                    summary="Escalate safely without execution.",
                )
            else:
                value = CriticReport(
                    decision=CriticDecision.ACCEPT,
                    summary="The advisory proposal is supported for deterministic review.",
                )
        else:
            raise AssertionError(f"unsupported offline response model: {response_model}")
        return cast(OutputT, value)


class OfflineTrajectoryTools:
    def __init__(self, case: AgentTrajectoryCase | None = None) -> None:
        self.case = case

    def execute(self, role: AgentRole, request: ToolRequest) -> AgentToolResult:
        if request.tool_name not in {"get_case", "get_it_snapshot", "search_policies"}:
            raise AssertionError(f"forbidden offline tool: {request.tool_name}")
        data: dict[str, object]
        if request.tool_name == "get_case":
            data = {
                "case_id": request.arguments.resource_id or "SYNTHETIC-CASE",
                "issues": [{"issue_type": "duplicate_charge", "status": "open"}],
                "payment_evidence": {
                    "capture_count": 2,
                    "matching_order": True,
                    "currency": "USD",
                    "amounts_match": True,
                    "prior_refund_exists": False,
                },
                "evidence_status": (
                    "conflicting_or_incomplete"
                    if self.case is not None
                    and self.case.scenario in {"revise_once", "escalate"}
                    else "current_and_complete"
                ),
                "evaluation_scenario": self.case.scenario if self.case is not None else "accept",
                "synthetic": True,
            }
        elif request.tool_name == "get_it_snapshot":
            data = {
                "access_state": "review_required",
                "identity_match": True,
                "mfa_enrolled": True,
                "manager_approval": "verified",
                "repository_owner_match": True,
                "evaluation_scenario": self.case.scenario if self.case is not None else "accept",
                "synthetic": True,
            }
        else:
            data = {
                "results": [
                    {
                        "chunk_id": "CHUNK-OFFLINE-1",
                        "policy_id": "POLICY-OFFLINE",
                        "version": 1,
                        "section": "Human review and deterministic controls",
                        "text": (
                            "A supported advisory proposal may proceed to deterministic review. "
                            "Sensitive actions require human approval and fresh verification."
                        ),
                        "active": True,
                    }
                ],
                "synthetic": True,
            }
        return AgentToolResult(
            tool_name=request.tool_name,
            result_category=request.tool_name.removeprefix("get_"),
            source=f"offline://{request.tool_name}",
            observed_at=NOW,
            data=data,
        )


def run_offline_trajectory(
    case: AgentTrajectoryCase, *, memory_enabled: bool = False
) -> AgentTrajectoryObservation:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    store = AgentRunStore(factory)
    ledger = BudgetLedger(
        AgentBudget(
            max_agent_steps=20,
            max_model_calls=20,
            max_tool_calls=10,
            max_input_tokens=100_000,
            max_output_tokens=10_000,
        ),
        datetime.now(UTC),
    )
    provider = OfflineTrajectoryProvider(case)
    memory_store = ReviewedResolutionMemoryStore(factory)
    if memory_enabled:
        memory_store.promote(
            tenant_id="TENANT-EVALUATION",
            issue_type="duplicate_charge",
            evidence_pattern=["current record indicates a duplicate charge"],
            policy_versions={"POLICY-OFFLINE": 1},
            approved_resolution={"action": "review_duplicate", "requires_approval": True},
            verification_outcome="The deterministic fixture verified the bounded outcome.",
            reviewed_by="EVALUATION-FIXTURE",
        )
    runtime = MultiAgentReasoningRuntime(
        invoker=AgentInvoker(provider=provider, store=store, ledger=ledger),
        tools=OfflineTrajectoryTools(),
        run_store=store,
        ledger=ledger,
        memory_retriever=memory_store if memory_enabled else None,
    )
    started = perf_counter()
    result = HierarchicalAgentOrchestrator(runtime).run(
        workflow_id=f"WF-{case.evaluation_id}",
        case_id=case.evaluation_id,
        tenant_id="TENANT-EVALUATION",
        domain=case.domain,
        objective=case.objective,
        trace_id=(case.evaluation_id.lower().encode().hex() + "0" * 32)[:32],
    )
    latency_ms = (perf_counter() - started) * 1_000
    runs = store.list_for_workflow(result.workflow_id)
    tools = store.list_tool_calls_for_workflow(result.workflow_id)
    critic_decisions = [
        CriticDecision(str(run.structured_output["decision"]))
        for run in runs
        if run.role == AgentRole.CRITIC and run.structured_output is not None
    ]
    observation = AgentTrajectoryObservation(
        status=result.status,
        roles=[run.role for run in runs],
        tools=[tool.tool_name for tool in tools],
        critic_decisions=critic_decisions,
        replan_count=result.replan_count,
        model_calls=result.agent_call_count,
        tool_calls=result.tool_call_count,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        latency_ms=latency_ms,
    )
    engine.dispose()
    return observation
