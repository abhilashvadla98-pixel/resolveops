from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from resolveops.agents.budgets import AgentBudgetExceeded, BudgetLedger
from resolveops.agents.models import (
    AgentBudget,
    AgentRole,
    AgentRunStatus,
    CriticDecision,
    CriticReport,
    InvestigationTurn,
    ToolCallStatus,
)
from resolveops.agents.permissions import AgentToolDenied, require_agent_tool
from resolveops.agents.persistence import AgentRunStore, safe_context_hash
from resolveops.database.agent_records import AgentRunRecord, AgentToolCallRecord
from resolveops.database.base import Base

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
