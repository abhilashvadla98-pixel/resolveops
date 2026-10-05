from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from resolveops.database.base import Base
from resolveops.database.records import OrderRecord, RefundRecord
from resolveops.database.seed import seed_all
from resolveops.database.session import create_session_factory
from resolveops.database.workflow_records import WorkflowRunRecord
from resolveops.events.models import RefundStatusChangedEvent
from resolveops.events.processor import RefundEventProcessor
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.knowledge.ingestion import ingest_directory
from resolveops.models.case import CaseIssueType, IssueFinding
from resolveops.models.order import OrderStatus
from resolveops.models.refund import RefundKind
from resolveops.operations.actions import ActionTools
from resolveops.operations.models import Actor, ActorRole
from resolveops.operations.proposals import investigate_issue
from resolveops.workflows.case_state import refresh_refund_result
from resolveops.workflows.customer_issue import CustomerIssueWorkflow
from resolveops.workflows.lifecycle import WorkflowLifecycleStore
from resolveops.workflows.models import (
    ApprovalDecisionType,
    WorkflowApprovalDecision,
    WorkflowOutcome,
    WorkflowPause,
    WorkflowRequest,
    WorkflowResult,
)


def seeded_factory() -> tuple[Engine, sessionmaker[Session]]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory.begin() as session:
        seed_all(session)
    return engine, factory


def test_incorrect_refund_amount_proposes_only_verified_remaining_balance() -> None:
    engine, factory = seeded_factory()
    try:
        with factory() as session:
            result = investigate_issue(session, "CASE-DEMO-I", "ISSUE-DEMO-I")

        assert result.finding == IssueFinding.CONFIRMED
        assert result.proposal is not None
        assert result.proposal.payment_id == "PAY-DEMO-I-1"
        assert result.proposal.return_id == "RET-DEMO-I"
        assert result.proposal.amount == Decimal("80.00")
        assert result.proposal.kind == RefundKind.RETURN
    finally:
        engine.dispose()


def test_cancelled_order_charge_proposes_one_full_captured_refund() -> None:
    engine, factory = seeded_factory()
    try:
        with factory() as session:
            result = investigate_issue(session, "CASE-DEMO-J", "ISSUE-DEMO-J")

        assert result.finding == IssueFinding.CONFIRMED
        assert result.proposal is not None
        assert result.proposal.payment_id == "PAY-DEMO-J-1"
        assert result.proposal.amount == Decimal("120.00")
        assert result.proposal.kind == RefundKind.CANCELLED_ORDER
    finally:
        engine.dispose()


def test_incorrect_refund_without_a_prior_refund_stops_for_review() -> None:
    engine, factory = seeded_factory()
    try:
        with factory.begin() as session:
            prior = session.get(RefundRecord, "REF-DEMO-I-PARTIAL")
            assert prior is not None
            session.delete(prior)
        with factory() as session:
            result = investigate_issue(session, "CASE-DEMO-I", "ISSUE-DEMO-I")

        assert result.finding == IssueFinding.UNDETERMINED
        assert result.proposal is None
        assert result.error is not None and "missing-refund complaint" in result.error
    finally:
        engine.dispose()


def test_cancelled_order_charge_stops_when_order_is_not_cancelled() -> None:
    engine, factory = seeded_factory()
    try:
        with factory.begin() as session:
            order = session.get(OrderRecord, "ORD-DEMO-J")
            assert order is not None
            order.status = OrderStatus.DELIVERED
        with factory() as session:
            result = investigate_issue(session, "CASE-DEMO-J", "ISSUE-DEMO-J")

        assert result.finding == IssueFinding.REJECTED
        assert result.proposal is None
    finally:
        engine.dispose()


def test_new_customer_issues_use_the_integrated_specialist_graph() -> None:
    for issue_type in (
        CaseIssueType.INCORRECT_REFUND_AMOUNT,
        CaseIssueType.CANCELLED_ORDER_CHARGE,
    ):
        assert CustomerIssueWorkflow._requires_multi_agent(
            {
                "case_issue_count": 1,
                "issue_type": issue_type,
                "investigation_error": None,
            }
        )


@pytest.mark.parametrize(
    ("case_id", "issue_id", "expected_amount", "expected_kind"),
    [
        ("CASE-DEMO-I", "ISSUE-DEMO-I", Decimal("80.00"), RefundKind.RETURN),
        (
            "CASE-DEMO-J",
            "ISSUE-DEMO-J",
            Decimal("120.00"),
            RefundKind.CANCELLED_ORDER,
        ),
    ],
)
def test_new_customer_issue_completes_approval_action_and_fresh_settlement(
    case_id: str,
    issue_id: str,
    expected_amount: Decimal,
    expected_kind: RefundKind,
) -> None:
    engine, factory = seeded_factory()
    now = datetime(2026, 10, 5, 15, 0, tzinfo=UTC)
    embedding = FeatureHashEmbeddingProvider(dimensions=128)
    with factory.begin() as session:
        ingest_directory(
            session,
            Path("domain_packs/customer_operations/policies"),
            embedding,
            ingested_at=now,
        )
    lifecycle = WorkflowLifecycleStore(factory, clock=lambda: now)
    checkpointer = InMemorySaver()
    workflow = CustomerIssueWorkflow(
        factory,
        embedding,
        action_tools=ActionTools(factory, clock=lambda: now),
        checkpointer=checkpointer,
        lifecycle_store=lifecycle,
        clock=lambda: now,
    )
    try:
        paused = workflow.start(
            WorkflowRequest(
                workflow_id=f"WF-{issue_id}",
                case_id=case_id,
                issue_id=issue_id,
                actor=Actor(actor_id="OPERATOR-1", role=ActorRole.OPERATOR),
                investigation_only=True,
            )
        )
        assert isinstance(paused, WorkflowPause)
        assert paused.approval.amount == expected_amount

        submitted = workflow.resume(
            WorkflowApprovalDecision(
                approval_id=paused.approval.approval_id,
                decision=ApprovalDecisionType.APPROVE,
                actor=Actor(actor_id="APPROVER-1", role=ActorRole.APPROVER),
                note="Verified evidence, calculation and active policy.",
            )
        )
        assert isinstance(submitted, WorkflowResult)
        assert submitted.outcome == WorkflowOutcome.REFUND_SUBMITTED, (
            submitted.error_code,
            submitted.error_message,
            submitted.node_history,
        )
        assert submitted.operation is not None
        with factory() as session:
            refund = session.get(RefundRecord, submitted.operation.resource_id)
            assert refund is not None
            assert refund.amount == expected_amount
            assert refund.kind == expected_kind

        settled_at = now + timedelta(minutes=1)
        RefundEventProcessor(factory, clock=lambda: settled_at).process(
            RefundStatusChangedEvent.model_validate(
                {
                    "event_id": f"EVT-{issue_id}",
                    "source": "payment-provider-sandbox",
                    "occurred_at": settled_at,
                    "data": {
                        "refund_id": submitted.operation.resource_id,
                        "provider_reference": f"PROVIDER-{issue_id}",
                        "status": "completed",
                        "completed_at": settled_at,
                    },
                }
            )
        )
        with factory() as session:
            stored_refund = session.get(RefundRecord, submitted.operation.resource_id)
            stored_run = session.get(WorkflowRunRecord, f"WF-{issue_id}")
            assert stored_refund is not None
            assert stored_run is not None
            assert stored_refund.status.value == "completed"
            related_refunds = list(
                session.scalars(select(RefundRecord).where(RefundRecord.issue_id == issue_id))
            )
        refreshed = refresh_refund_result(factory, submitted, lambda: settled_at)
        assert refreshed.outcome == WorkflowOutcome.REFUND_SETTLED, (
            refreshed.error_code,
            refreshed.error_message,
            stored_run.status,
            stored_run.outcome,
            [(item.refund_id, item.status.value) for item in related_refunds],
        )
        final = workflow.get_execution(f"WF-{issue_id}")
        assert isinstance(final, WorkflowResult)
        assert final.outcome == WorkflowOutcome.REFUND_SETTLED
    finally:
        engine.dispose()
