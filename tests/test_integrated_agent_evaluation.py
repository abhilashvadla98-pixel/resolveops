import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar, cast

import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine

from resolveops.agents.budgets import BudgetLedger
from resolveops.agents.context import AgentContext
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
    ProposedAction,
    ResolutionProposal,
    SupervisorPlan,
    ToolArguments,
    ToolRequest,
)
from resolveops.agents.persistence import AgentRunStore
from resolveops.agents.runtime import MultiAgentReasoningRuntime
from resolveops.database.base import Base
from resolveops.database.seed import seed_all
from resolveops.database.session import create_session_factory
from resolveops.evaluation.integrated_agents import (
    IntegratedTask,
    RecordingReadTools,
    load_integrated_tasks,
    run_integrated_trial,
    summarize_integrated_trials,
)
from resolveops.evaluation.offline_agents import NOW
from resolveops.reasoning.errors import ReasoningProviderError

DATASET = Path("evals/integrated/cases.jsonl")
POLICIES = Path("domain_packs/customer_operations/policies")
OutputT = TypeVar("OutputT", bound=BaseModel)


class SourceReadingTestProvider:
    """A test double, never model-quality evidence; no dataset/expected-answer access."""

    provider_name = "scripted-test-only"
    model_name = "source-reading-contract"
    last_usage = None

    def __init__(self, *, fabricate: bool = False) -> None:
        self.fabricate = fabricate
        self.contexts: list[dict[str, object]] = []

    def invoke(
        self,
        *,
        instructions: str,
        context: BaseModel | dict[str, object],
        response_model: type[OutputT],
    ) -> OutputT:
        context = cast(AgentContext, context)
        self.contexts.append(context.model_dump(mode="json"))
        value: BaseModel
        if response_model is SupervisorPlan:
            value = SupervisorPlan(
                goal="Investigate the two reported billing issues.",
                issues=["duplicate charge", "return refund"],
                plan_steps=[
                    PlanStep(
                        step_id="read",
                        objective="Read linked records",
                        assigned_role=AgentRole.INVESTIGATION,
                    )
                ],
                required_evidence=["linked order, captures, returns, prior refunds"],
                delegations=[
                    AgentRole.INVESTIGATION,
                    AgentRole.POLICY,
                    AgentRole.RESOLUTION,
                    AgentRole.CRITIC,
                ],
                parallelizable_tasks=[],
                missing_information=["current source records"],
                next_agent=AgentRole.INVESTIGATION,
                stopping_condition="Critic review of supported proposal",
            )
        elif response_model is InvestigationTurn:
            observations = context.tool_results
            queue: list[tuple[str, str]] = [("get_case", context.case_id)]
            case = next(
                (row["data"] for row in observations if row["tool_name"] == "get_case"), None
            )
            if isinstance(case, dict):
                queue.append(("get_order", str(case["order_id"])))
            order = next(
                (row["data"] for row in observations if row["tool_name"] == "get_order"), None
            )
            if isinstance(order, dict):
                for category in ("payment", "return", "refund"):
                    for identifier in order[f"{category}_ids"]:
                        queue.append((f"get_{category}", str(identifier)))
            if len(observations) < len(queue):
                name, identifier = queue[len(observations)]
                value = InvestigationTurn(
                    confidence=0.2,
                    complete=False,
                    next_tool=ToolRequest(
                        tool_name=name,
                        arguments=ToolArguments(resource_id=identifier),
                        purpose="Read linked source evidence.",
                    ),
                )
            else:
                facts = []
                for observed in observations:
                    payload = cast(dict[str, object], observed["data"])
                    field = "amount" if "amount" in payload else "status"
                    facts.append(
                        EvidenceFact(
                            evidence_id="EOBS-FABRICATED"
                            if self.fabricate
                            else str(observed["observation_id"]),
                            source=str(observed["source"]),
                            observed_at=str(observed["observed_at"]),
                            fact="Captured source value",
                            source_field=f"/{field}",
                            source_value_json=json.dumps(payload[field]),
                        )
                    )
                value = InvestigationTurn(
                    confidence=0.9,
                    complete=True,
                    facts=facts,
                    evidence_ids=list(dict.fromkeys(fact.evidence_id for fact in facts)),
                    source_provenance=list(dict.fromkeys(fact.source for fact in facts)),
                )
        elif response_model is PolicyTurn:
            if not context.policy_results:
                value = PolicyTurn(
                    complete=False,
                    policy_interpretation="Current policy required",
                    next_query="duplicate charge captured payment obligations and existing return refund",
                )
            else:
                chunks = context.policy_results[-1]["data"]["results"]
                selected = [
                    row
                    for row in chunks
                    if row["document_id"] in {"POLICY-DUPLICATE-CHARGE", "POLICY-RETURN-REFUND"}
                ]
                value = PolicyTurn(
                    complete=True,
                    policy_interpretation="Read relevant duplicate and return rules.",
                    citations=[row["chunk_id"] for row in selected],
                    policy_versions={
                        row["document_id"]: row["document_version"] for row in selected
                    },
                )
        elif response_model is ResolutionProposal:
            reads = {row["tool_name"]: row["data"] for row in context.tool_results}
            case = reads["get_case"]
            payments = [
                row["data"] for row in context.tool_results if row["tool_name"] == "get_payment"
            ]
            payment = max(payments, key=lambda row: row["captured_at"])
            policy = context.prior_outputs[1]
            evidence_ids = context.facts[0]["evidence_ids"]
            resolutions = []
            actions = []
            for issue in case["issues"]:
                is_duplicate = issue["issue_type"] == "duplicate_charge"
                resolutions.append(
                    IssueResolution(
                        issue_id=issue["issue_id"],
                        disposition="refund" if is_duplicate else "wait",
                        recommendation="Review the extra capture"
                        if is_duplicate
                        else "Monitor the existing return refund",
                        evidence_ids=evidence_ids,
                        policy_citations=policy["citations"],
                    )
                )
                if is_duplicate:
                    actions.append(
                        ProposedAction(
                            action_type="issue_refund",
                            issue_id=issue["issue_id"],
                            resource_id=payment["payment_id"],
                            amount=payment["amount"],
                            requires_approval=True,
                        )
                    )
            value = ResolutionProposal(
                issue_resolutions=resolutions,
                proposed_actions=actions,
                evidence_support=evidence_ids,
                policy_support=policy["citations"],
                escalation_needed=False,
            )
        else:
            assert response_model is CriticReport
            value = CriticReport(
                decision=CriticDecision.ACCEPT,
                summary="Test double accepts a schema-correct recommendation; production controls remain authoritative.",
            )
        return cast(OutputT, value)


class SafetyStopTestProvider(SourceReadingTestProvider):
    def __init__(self, *, stop_at: str) -> None:
        super().__init__()
        self.stop_at = stop_at

    def invoke(
        self,
        *,
        instructions: str,
        context: BaseModel | dict[str, object],
        response_model: type[OutputT],
    ) -> OutputT:
        value = super().invoke(
            instructions=instructions, context=context, response_model=response_model
        )
        if self.stop_at == "evidence" and isinstance(value, InvestigationTurn) and value.complete:
            value = value.model_copy(
                update={
                    "contradictions": [
                        "Source records conflict; operator reconciliation is required."
                    ]
                }
            )
        elif self.stop_at == "policy" and isinstance(value, PolicyTurn) and value.complete:
            value = value.model_copy(
                update={"missing_policy": True, "citations": [], "policy_versions": {}}
            )
        return cast(OutputT, value)


class MalformedOnceTestProvider(SourceReadingTestProvider):
    def __init__(self, *, always_fail: bool = False) -> None:
        super().__init__()
        self.failed_once = False
        self.always_fail = always_fail

    def invoke(
        self,
        *,
        instructions: str,
        context: BaseModel | dict[str, object],
        response_model: type[OutputT],
    ) -> OutputT:
        if response_model is InvestigationTurn and (not self.failed_once or self.always_fail):
            self.failed_once = True
            raise ReasoningProviderError(
                "agent_output_invalid", "An incomplete investigation must request its next tool."
            )
        return super().invoke(
            instructions=instructions, context=context, response_model=response_model
        )


class InvalidReferenceTestProvider(MalformedOnceTestProvider):
    def __init__(self, *, always_bad: bool, earlier_repair: bool) -> None:
        super().__init__()
        self.failed_once = not earlier_repair
        self.always_bad = always_bad
        self.resolution_calls = 0

    def invoke(self, *, instructions, context, response_model):  # type: ignore[no-untyped-def]
        value = super().invoke(
            instructions=instructions, context=context, response_model=response_model
        )
        if isinstance(value, ResolutionProposal):
            self.resolution_calls += 1
            if self.resolution_calls == 1 or self.always_bad:
                return value.model_copy(update={"evidence_support": ["EVD-UNTRUSTED-SNAPSHOT"]})
        return value


@pytest.mark.parametrize(
    "task", load_integrated_tasks(DATASET), ids=lambda task: task.evaluation_id
)
def test_rules_baseline_through_new_intake_approval_and_settlement(task: IntegratedTask) -> None:
    record = run_integrated_trial(task, 1, policy_directory=POLICIES)
    assert record["passed"], record["checks"]
    assert record["model_calls"] == 0
    assert record["tool_call_count"] == 0
    assert record["execution_mode"] == "rules_only"
    assert record["approval_review"] == "synthetic_test_decision_not_human_review"


def test_actual_tools_are_case_bound_and_discover_cross_case_refunds() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory.begin() as session:
        seed_all(session)
    tools = RecordingReadTools(factory, lambda: NOW)

    def read(name: str, identifier: str):  # type: ignore[no-untyped-def]
        return tools.execute(
            AgentRole.INVESTIGATION,
            ToolRequest(
                tool_name=name,
                arguments=ToolArguments(resource_id=identifier),
                purpose="Read scoped record.",
            ),
        )

    with pytest.raises(PermissionError, match="scoped case"):
        read("get_order", "ORD-48391")
    read("get_case", "CASE-1001")
    order = read("get_order", "ORD-48391")
    assert order.data["payment_ids"] == ["PAY-1001", "PAY-1002"]
    assert order.data["return_ids"] == ["RET-3001"]
    assert order.data["refund_ids"] == ["REF-2001"]
    with pytest.raises(PermissionError, match="investigation scope"):
        read("get_case", "CASE-DEMO-A")
    with pytest.raises(PermissionError, match="scoped case order"):
        read("get_order", "ORD-DEMO-A")
    with pytest.raises(PermissionError, match="scoped case order"):
        read("get_customer", "CUST-DEMO-A")
    with pytest.raises(PermissionError, match="bound investigation"):
        read("get_it_snapshot", "ITCASE-2001")
    with pytest.raises(ValueError, match="missing required source reads"):
        tools.require_investigation_coverage(
            [row for row in [read("get_case", "CASE-1001"), order]]
        )
    model_payload = json.dumps(tools.observations)
    for hidden in ("expected_outcome", "expected_new_refunds", "evaluation_scenario"):
        assert hidden not in model_payload
    engine.dispose()


@pytest.mark.parametrize("fabricate", [False, True])
def test_normal_workflow_consumes_actual_multi_role_read_tools(fabricate: bool) -> None:
    provider = SourceReadingTestProvider(fabricate=fabricate)

    def builder(factory):  # type: ignore[no-untyped-def]
        store = AgentRunStore(factory)
        ledger = BudgetLedger(
            AgentBudget(max_agent_steps=16, max_model_calls=16), datetime.now(UTC)
        )
        return MultiAgentReasoningRuntime(
            invoker=AgentInvoker(provider=provider, store=store, ledger=ledger),
            tools=RecordingReadTools(factory, lambda: datetime.now(UTC)),
            run_store=store,
            ledger=ledger,
            max_investigation_turns=8,
        )

    record = run_integrated_trial(
        load_integrated_tasks(DATASET)[0],
        1,
        policy_directory=POLICIES,
        runtime_builder=builder,
        execution_mode="scripted_contract_not_live_model",
    )
    if fabricate:
        assert not record["passed"]
        assert not record["new_refunds"]
        assert record["workflow_result"]["outcome"] == "needs_review"
    else:
        assert record["passed"], (record["checks"], record["error"], record["workflow_result"])
        assert record["model_calls"] >= 10
        assert len(record["tool_observations"]) >= 7
        assert record["workflow_result"]["outcome"] == "refund_submitted"
        assert record["new_refunds"][0]["status"] == "completed"
    payload = json.dumps(provider.contexts)
    for hidden in ("expected_outcome", "expected_new_refunds", "evaluation_scenario", "IC-01"):
        assert hidden not in payload


@pytest.mark.parametrize("stop_at", ["evidence", "policy"])
def test_early_stop_skips_unnecessary_roles_without_inventing_outputs(stop_at: str) -> None:
    provider = SafetyStopTestProvider(stop_at=stop_at)

    def builder(factory):  # type: ignore[no-untyped-def]
        store = AgentRunStore(factory)
        ledger = BudgetLedger(
            AgentBudget(max_agent_steps=16, max_model_calls=16), datetime.now(UTC)
        )
        return MultiAgentReasoningRuntime(
            invoker=AgentInvoker(provider=provider, store=store, ledger=ledger),
            tools=RecordingReadTools(factory, lambda: datetime.now(UTC)),
            run_store=store,
            ledger=ledger,
            max_investigation_turns=8,
        )

    record = run_integrated_trial(
        load_integrated_tasks(DATASET)[0],
        1,
        policy_directory=POLICIES,
        runtime_builder=builder,
        execution_mode="scripted_contract_not_live_model",
    )
    assert not record["new_refunds"]
    result = record["workflow_result"]
    assert result["outcome"] == "needs_review"
    assessment = result["agent_assessment"]
    assert assessment["status"] == "escalated"
    assert assessment["stop_reason"]
    assert assessment["resolution"] is None
    assert assessment["critic"] is None
    skipped = (
        ["policy", "resolution", "critic"] if stop_at == "evidence" else ["resolution", "critic"]
    )
    assert assessment["skipped_roles"] == skipped
    assert not set(skipped).intersection(row["role"] for row in record["agent_runs"])
    assert (
        assessment["policy"] is None
        if stop_at == "evidence"
        else assessment["policy"]["missing_policy"]
    )


@pytest.mark.parametrize("always_fail", [False, True])
def test_one_schema_repair_is_counted_and_repeated_failure_stops(always_fail: bool) -> None:
    provider = MalformedOnceTestProvider(always_fail=always_fail)

    def builder(factory):  # type: ignore[no-untyped-def]
        store = AgentRunStore(factory)
        ledger = BudgetLedger(
            AgentBudget(max_agent_steps=16, max_model_calls=16), datetime.now(UTC)
        )
        return MultiAgentReasoningRuntime(
            invoker=AgentInvoker(provider=provider, store=store, ledger=ledger),
            tools=RecordingReadTools(factory, lambda: datetime.now(UTC)),
            run_store=store,
            ledger=ledger,
            max_investigation_turns=8,
        )

    record = run_integrated_trial(
        load_integrated_tasks(DATASET)[0],
        1,
        policy_directory=POLICIES,
        runtime_builder=builder,
        execution_mode="scripted_contract_not_live_model",
    )
    failed = [row for row in record["agent_runs"] if row["status"] == "failed"]
    assert len(failed) == (2 if always_fail else 1)
    assert record["model_calls"] == record["usage"]["model_calls"]
    if always_fail:
        assert record["model_calls"] == 3  # supervisor, invalid response, one repair
        assert not record["new_refunds"]
        assert summarize_integrated_trials([record]) == {
            "completed_trials": 0,
            "trials_without_provider_failures": 0,
            "correct_trials": 0,
        }
    else:
        assert record["passed"], record["checks"]
        assert any("schema validation" in json.dumps(context) for context in provider.contexts)
        assert summarize_integrated_trials([record]) == {
            "completed_trials": 1,
            "trials_without_provider_failures": 0,
            "correct_trials": 1,
        }


def test_completed_trials_are_not_conflated_with_correctness_or_clean_calls() -> None:
    record = {
        "error": None,
        "workflow_result": {"outcome": "needs_review"},
        "checks": {"agent_executed_when_configured": True},
        "provider_failures": [],
        "passed": False,
    }
    assert summarize_integrated_trials([record]) == {
        "completed_trials": 1,
        "trials_without_provider_failures": 1,
        "correct_trials": 0,
    }
    record["workflow_result"] = None
    assert summarize_integrated_trials([record])["completed_trials"] == 0


@pytest.mark.parametrize(
    "always_bad,earlier_repair", [(False, False), (True, False), (False, True)]
)
def test_resolution_repair_is_single_shared_budget(always_bad: bool, earlier_repair: bool) -> None:
    provider = InvalidReferenceTestProvider(always_bad=always_bad, earlier_repair=earlier_repair)

    def builder(factory):  # type: ignore[no-untyped-def]
        store = AgentRunStore(factory)
        ledger = BudgetLedger(
            AgentBudget(max_agent_steps=16, max_model_calls=16), datetime.now(UTC)
        )
        return MultiAgentReasoningRuntime(
            invoker=AgentInvoker(provider=provider, store=store, ledger=ledger),
            tools=RecordingReadTools(factory, lambda: datetime.now(UTC)),
            run_store=store,
            ledger=ledger,
            max_investigation_turns=8,
        )

    record = run_integrated_trial(
        load_integrated_tasks(DATASET)[0],
        1,
        policy_directory=POLICIES,
        runtime_builder=builder,
        execution_mode="scripted_contract_not_live_model",
    )
    assert provider.resolution_calls == (1 if earlier_repair else 2)
    assert record["passed"] == (not always_bad and not earlier_repair)
    if always_bad or earlier_repair:
        assert not record["new_refunds"]
    contexts = [row for row in provider.contexts if row["role"] == "resolution"]
    assert contexts[0]["valid_evidence_ids"]
    assert contexts[0]["valid_policy_citation_ids"]
    if len(contexts) == 2:
        feedback = json.dumps(contexts[1]["required_evidence"])
        assert "unobserved evidence" in feedback
        assert "1499" not in feedback
