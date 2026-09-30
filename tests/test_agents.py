from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from resolveops.agents.budgets import AgentBudgetExceeded, BudgetLedger
from resolveops.agents.context import AgentContextBuilder
from resolveops.agents.invocation import AgentInvoker
from resolveops.agents.models import (
    AgentBudget,
    AgentDomain,
    AgentRole,
    AgentRunStatus,
    CriticDecision,
    CriticReport,
    EvidenceFact,
    InvestigationTurn,
    IssueResolution,
    PlanStep,
    PolicyTurn,
    ResolutionProposal,
    SupervisorPlan,
    ToolCallStatus,
    ToolRequest,
)
from resolveops.agents.permissions import AgentToolDenied, require_agent_tool
from resolveops.agents.persistence import AgentRunStore, safe_context_hash
from resolveops.agents.runtime import MultiAgentReasoningRuntime
from resolveops.agents.tools import AgentToolResult
from resolveops.database.agent_records import AgentRunRecord, AgentToolCallRecord
from resolveops.database.base import Base
from resolveops.memory.store import ReviewedResolutionMemoryStore
from resolveops.orchestration.graph import HierarchicalAgentOrchestrator

NOW = datetime(2026, 9, 29, 12, tzinfo=UTC)


def test_agent_outputs_enforce_stop_and_independent_critic_contracts() -> None:
    with pytest.raises(ValueError, match="completed investigation"):
        InvestigationTurn(
            facts=[],
            evidence_ids=[],
            contradictions=[],
            missing_evidence=[],
            confidence=1,
            source_provenance=[],
            recommended_next_investigation=None,
            next_tool={
                "tool_name": "get_case",
                "arguments": {"case_id": "CASE-1"},
                "purpose": "Read the case",
            },
            complete=True,
        )
    with pytest.raises(ValueError, match="accepting critic"):
        CriticReport(
            decision=CriticDecision.ACCEPT,
            unsupported_claims=["Unsupported"],
            summary="The proposal is not supported.",
        )


def test_agent_tool_allowlists_block_sensitive_or_unrelated_tools() -> None:
    require_agent_tool(AgentRole.INVESTIGATION, "get_payment")
    with pytest.raises(AgentToolDenied):
        require_agent_tool(AgentRole.INVESTIGATION, "create_refund")
    with pytest.raises(AgentToolDenied):
        require_agent_tool(AgentRole.SUPERVISOR, "get_case")


def test_budget_ledger_stops_before_excess_model_or_tool_use() -> None:
    ledger = BudgetLedger(
        AgentBudget(max_model_calls=5, max_agent_steps=5, max_tool_calls=1), datetime.now(UTC)
    )
    ledger.consume_tool_call()
    with pytest.raises(AgentBudgetExceeded, match="tool_call_budget_exceeded"):
        ledger.consume_tool_call()
    assert ledger.usage.tool_calls == 1


def test_budget_ledger_enforces_wall_clock() -> None:
    ledger = BudgetLedger(AgentBudget(max_wall_clock_seconds=10), NOW)
    with pytest.raises(AgentBudgetExceeded, match="wall_clock_budget_exceeded"):
        ledger.check_time(NOW + timedelta(seconds=11))


def test_agent_and_tool_runs_are_durable_without_raw_arguments() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    store = AgentRunStore(factory, clock=lambda: NOW)
    context = {"case_id": "CASE-1", "masked_customer": "A***"}
    run = store.start(
        tenant_id="TENANT-A",
        workflow_id="WF-1",
        role=AgentRole.INVESTIGATION,
        prompt_version="investigation-v1",
        schema_version="investigation-turn-v1",
        provider="test",
        model="structured-test",
        context_hash=safe_context_hash(context),
        trace_id="a" * 32,
    )
    tool = store.start_tool_call(
        tenant_id="TENANT-A",
        agent_run_id=run.agent_run_id,
        tool_name="get_payment",
        arguments={"payment_id": "PAY-SECRET-1"},
    )
    finished_tool = store.finish_tool_call(
        tool.tool_call_id,
        status=ToolCallStatus.COMPLETED,
        result_category="payment",
    )
    finished = store.finish(
        run.agent_run_id,
        output={"complete": True, "confidence": 1.0},
        input_tokens=80,
        output_tokens=20,
    )

    assert finished.status == AgentRunStatus.COMPLETED
    assert finished.tool_call_count == 1
    assert finished_tool.argument_keys == ["payment_id"]
    with factory() as session:
        stored_tool = session.scalar(select(AgentToolCallRecord))
        stored_run = session.scalar(select(AgentRunRecord))
        assert stored_tool is not None
        assert "PAY-SECRET-1" not in stored_tool.argument_hash
        assert stored_run is not None
        assert stored_run.structured_output == {"complete": True, "confidence": 1.0}


class ScriptedProvider:
    provider_name = "scripted"
    model_name = "multi-agent-test"
    last_usage = None

    def __init__(self) -> None:
        self.roles: list[str] = []
        self.investigation_calls = 0
        self.policy_calls = 0

    def invoke(self, *, instructions, context, response_model):  # type: ignore[no-untyped-def]
        self.roles.append(response_model.__name__)
        if response_model is SupervisorPlan:
            return SupervisorPlan(
                goal="Resolve the reported duplicate payment safely.",
                issues=["duplicate payment"],
                plan_steps=[
                    PlanStep(
                        step_id="investigate",
                        objective="Read payment evidence",
                        assigned_role=AgentRole.INVESTIGATION,
                    ),
                    PlanStep(
                        step_id="policy",
                        objective="Find active refund policy",
                        assigned_role=AgentRole.POLICY,
                        can_run_in_parallel=True,
                    ),
                ],
                required_evidence=["case and payment state"],
                delegations=[
                    AgentRole.INVESTIGATION,
                    AgentRole.POLICY,
                    AgentRole.RESOLUTION,
                    AgentRole.CRITIC,
                ],
                parallelizable_tasks=["policy"],
                missing_information=["payment state"],
                next_agent=AgentRole.INVESTIGATION,
                stopping_condition="Critic accepts a supported proposal.",
            )
        if response_model is InvestigationTurn:
            self.investigation_calls += 1
            if self.investigation_calls == 1:
                return InvestigationTurn(
                    confidence=0.2,
                    missing_evidence=["case state"],
                    recommended_next_investigation="Read the case",
                    next_tool=ToolRequest(
                        tool_name="get_case",
                        arguments={"resource_id": "CASE-1"},
                        purpose="Inspect linked payment identifiers",
                    ),
                    complete=False,
                )
            return InvestigationTurn(
                facts=[
                    EvidenceFact(
                        evidence_id="E-CASE-1",
                        fact="Two captured payments are linked to the issue.",
                        source="resolveops://case/CASE-1",
                        observed_at=NOW,
                    )
                ],
                evidence_ids=["E-CASE-1"],
                confidence=0.95,
                source_provenance=["resolveops://case/CASE-1"],
                complete=True,
            )
        if response_model is PolicyTurn:
            self.policy_calls += 1
            if self.policy_calls == 1:
                return PolicyTurn(
                    policy_interpretation="Policy evidence has not been retrieved.",
                    next_query="duplicate captured payment refund",
                    complete=False,
                )
            return PolicyTurn(
                applicable_policy="Duplicate captured payments may be refunded after verification.",
                citations=["CHUNK-1"],
                policy_versions={"POLICY-1": 1},
                supporting_sections=["Duplicate payments"],
                policy_interpretation="The active policy supports review of one duplicate capture.",
                complete=True,
            )
        if response_model is ResolutionProposal:
            return ResolutionProposal(
                issue_resolutions=[
                    IssueResolution(
                        issue_id="ISSUE-1",
                        recommendation="Refund only the verified duplicate capture.",
                        evidence_ids=["E-CASE-1"],
                        policy_citations=["CHUNK-1"],
                    )
                ],
                evidence_support=["E-CASE-1"],
                policy_support=["CHUNK-1"],
                escalation_needed=False,
            )
        if response_model is CriticReport:
            return CriticReport(
                decision=CriticDecision.ACCEPT,
                expected_state_reached=None,
                summary="The proposal is supported and remains advisory.",
            )
        raise AssertionError(response_model)


class ScriptedTools:
    def execute(self, role: AgentRole, request: ToolRequest) -> AgentToolResult:
        assert request.tool_name in {"get_case", "search_policies"}
        return AgentToolResult(
            tool_name=request.tool_name,
            result_category="case" if request.tool_name == "get_case" else "policy_results",
            source=f"test://{request.tool_name}",
            observed_at=NOW,
            data={"verified": True},
        )


def test_true_multi_agent_runtime_invokes_distinct_roles_tools_and_handoffs() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    store = AgentRunStore(factory, clock=lambda: NOW)
    ledger = BudgetLedger(AgentBudget(max_model_calls=8, max_agent_steps=8), datetime.now(UTC))
    provider = ScriptedProvider()
    runtime = MultiAgentReasoningRuntime(
        invoker=AgentInvoker(provider=provider, store=store, ledger=ledger),
        tools=ScriptedTools(),
        run_store=store,
        ledger=ledger,
    )

    result = runtime.run(
        workflow_id="WF-MULTI-1",
        case_id="CASE-1",
        tenant_id="TENANT-A",
        domain=AgentDomain.CUSTOMER_OPERATIONS,
        objective="Resolve a suspected duplicate payment.",
        trace_id="b" * 32,
    )

    assert result.status == "ready_for_control_plane"
    assert result.agent_call_count == 7
    assert result.tool_call_count == 2
    assert provider.roles == [
        "SupervisorPlan",
        "InvestigationTurn",
        "InvestigationTurn",
        "PolicyTurn",
        "PolicyTurn",
        "ResolutionProposal",
        "CriticReport",
    ]
    stored = store.list_for_workflow("WF-MULTI-1")
    assert len(stored) == 7
    assert {item.role for item in stored} == set(AgentRole)
    assert sum(item.tool_call_count for item in stored) == 2


def test_context_builder_rejects_cross_tenant_evidence() -> None:
    with pytest.raises(ValueError, match="different tenant"):
        AgentContextBuilder().build(
            role=AgentRole.CRITIC,
            workflow_id="WF-1",
            case_id="CASE-1",
            tenant_id="TENANT-A",
            objective="Verify the proposal.",
            facts=[{"tenant_id": "TENANT-B", "fact": "wrong tenant"}],
            now=NOW,
        )


def test_hierarchical_langgraph_routes_customer_domain_through_specialists() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    store = AgentRunStore(factory, clock=lambda: NOW)
    ledger = BudgetLedger(AgentBudget(max_model_calls=8, max_agent_steps=8), datetime.now(UTC))
    provider = ScriptedProvider()
    runtime = MultiAgentReasoningRuntime(
        invoker=AgentInvoker(provider=provider, store=store, ledger=ledger),
        tools=ScriptedTools(),
        run_store=store,
        ledger=ledger,
    )

    result = HierarchicalAgentOrchestrator(runtime).run(
        workflow_id="WF-GRAPH-1",
        case_id="CASE-1",
        tenant_id="TENANT-A",
        domain=AgentDomain.CUSTOMER_OPERATIONS,
        objective="Resolve a suspected duplicate payment.",
        trace_id="c" * 32,
    )

    assert result.status == "ready_for_control_plane"
    assert result.supervisor.next_agent == AgentRole.INVESTIGATION
    assert result.critic.decision == CriticDecision.ACCEPT
    assert len(result.agent_run_ids) == 7


def test_reviewed_memory_is_explicit_tenant_scoped_and_advisory() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    store = ReviewedResolutionMemoryStore(factory, clock=lambda: NOW)
    promoted = store.promote(
        tenant_id="TENANT-A",
        issue_type="duplicate_charge",
        evidence_pattern=["two captured payments", "no existing refund"],
        policy_versions={"POLICY-1": 2},
        approved_resolution={"action": "refund_duplicate"},
        verification_outcome="refund record independently verified",
        reviewed_by="REVIEWER-1",
    )

    assert store.retrieve(tenant_id="TENANT-A", issue_type="duplicate_charge") == [promoted]
    assert store.retrieve(tenant_id="TENANT-B", issue_type="duplicate_charge") == []
