"""Synthetic service-level acceptance; no live model, bank, or deployed claims."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from resolveops.database.base import Base
from resolveops.database.records import RefundRecord
from resolveops.database.seed import seed_all
from resolveops.database.session import create_session_factory
from resolveops.database.store import CustomerOperationsStore
from resolveops.events.models import InboundEventStatus, RefundStatusChangedEvent
from resolveops.events.processor import RefundEventProcessor
from resolveops.intake.service import CaseIntakeService, IntakeRequest
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.knowledge.ingestion import ingest_directory
from resolveops.models.case import CaseIssueStatus, CaseIssueType, CaseStatus, IssueFinding
from resolveops.models.order import Order, OrderItem, OrderStatus
from resolveops.models.payment import Payment, PaymentStatus
from resolveops.models.refund import RefundKind, RefundStatus
from resolveops.models.returns import Return, ReturnItem, ReturnStatus
from resolveops.operations.models import Actor, ActorRole
from resolveops.workflows.customer_issue import CustomerIssueWorkflow
from resolveops.workflows.lifecycle import WorkflowLifecycleStore
from resolveops.workflows.models import (
    ApprovalDecisionType,
    WorkflowApprovalDecision,
    WorkflowLifecycleStatus,
    WorkflowOutcome,
    WorkflowPause,
    WorkflowRequest,
    WorkflowStatus,
)

NOW = datetime(2026, 10, 4, 15, tzinfo=UTC)
ORDER_ID = "ORD-COMBINED"
EXISTING_REFUND_ID = "REF-COMBINED-RETURN"


@pytest.fixture
def combined_store() -> Iterator[sessionmaker[Session]]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory.begin() as session:
        seed_all(session)
        store = CustomerOperationsStore(session)
        store.add_order(
            Order(
                order_id=ORDER_ID,
                customer_id="CUST-1001",
                status=OrderStatus.PARTIALLY_RETURNED,
                total_amount=Decimal("150.00"),
                currency="USD",
                created_at=NOW - timedelta(days=1),
                items=[
                    OrderItem(
                        order_item_id=f"ITEM-COMBINED-{sku}",
                        order_id=ORDER_ID,
                        sku=sku,
                        name=name,
                        quantity=1,
                        unit_price=Decimal(price),
                        currency="USD",
                    )
                    for sku, name, price in (
                        ("HEADPHONES", "Headphones", "120.00"),
                        ("ACCESSORY", "Retained accessory", "30.00"),
                    )
                ],
            )
        )
        session.flush()
        for index in (1, 2):
            store.add_payment(
                Payment(
                    payment_id=f"PAY-COMBINED-{index}",
                    order_id=ORDER_ID,
                    amount=Decimal("150.00"),
                    currency="USD",
                    status=PaymentStatus.CAPTURED,
                    created_at=NOW - timedelta(days=1),
                    captured_at=NOW - timedelta(hours=23) + timedelta(minutes=index),
                    obligation_id="OBL-COMBINED-150",
                    obligation_amount=Decimal("150.00"),
                )
            )
        store.add_return(
            Return(
                return_id="RET-COMBINED",
                order_id=ORDER_ID,
                customer_id="CUST-1001",
                status=ReturnStatus.RECEIVED,
                created_at=NOW - timedelta(hours=3),
                received_at=NOW - timedelta(hours=2),
                items=[
                    ReturnItem(
                        order_item_id="ITEM-COMBINED-HEADPHONES",
                        quantity=1,
                        reason="Returned headphones; retained accessory",
                    )
                ],
            )
        )
        session.flush()
        prior_case, _ = CaseIntakeService(session, clock=lambda: NOW - timedelta(hours=1)).submit(
            IntakeRequest(
                customer_id="CUST-1001",
                order_id=ORDER_ID,
                complaint="I returned the headphones but the refund is missing.",
                source_message_id="combined-prior-return",
            )
        )
        prior_issue = next(
            issue
            for issue in prior_case.issues
            if issue.issue_type == CaseIssueType.MISSING_RETURN_REFUND
        )
        session.add(
            RefundRecord(
                refund_id=EXISTING_REFUND_ID,
                payment_id="PAY-COMBINED-1",
                order_id=ORDER_ID,
                issue_id=prior_issue.issue_id,
                return_id="RET-COMBINED",
                amount=Decimal("120.00"),
                currency="USD",
                status=RefundStatus.PENDING,
                kind=RefundKind.RETURN,
                reason="Synthetic provider previously accepted the received headphones refund",
                created_at=NOW - timedelta(minutes=30),
                completed_at=None,
            )
        )
        ingest_directory(
            session,
            Path("domain_packs/customer_operations/policies"),
            FeatureHashEmbeddingProvider(dimensions=128),
            ingested_at=NOW,
        )
    yield factory
    engine.dispose()


@pytest.mark.parametrize("return_settles_first", [False, True])
def test_new_combined_complaint_keeps_existing_return_and_refunds_only_extra_capture(
    combined_store: sessionmaker[Session], return_settles_first: bool
) -> None:
    factory = combined_store
    with factory.begin() as session:
        intake = IntakeRequest(
            customer_id="CUST-1001",
            order_id=ORDER_ID,
            complaint=(
                "I was charged twice and returned the headphones but the refund is missing. "
                "Support said my refund started. Please check before refunding me again."
            ),
            source_message_id="combined-current-complaint",
        )
        service = CaseIntakeService(session, clock=lambda: NOW)
        case, _ = service.submit(intake)
        assert service.submit(intake)[0].case_id == case.case_id
    assert len(case.issues) == 2
    assert all(issue.finding == IssueFinding.UNDETERMINED for issue in case.issues)
    issues = {issue.issue_type: issue.issue_id for issue in case.issues}
    lifecycle = WorkflowLifecycleStore(factory, clock=lambda: NOW)
    workflow = CustomerIssueWorkflow(
        factory,
        FeatureHashEmbeddingProvider(dimensions=128),
        checkpointer=InMemorySaver(),
        lifecycle_store=lifecycle,
        clock=lambda: NOW,
    )

    def investigate(issue_type: CaseIssueType):
        return workflow.start(
            WorkflowRequest(
                workflow_id=f"WF-COMBINED-{issue_type.value}",
                case_id=case.case_id,
                issue_id=issues[issue_type],
                actor=Actor(actor_id="OPERATOR-COMBINED", role=ActorRole.OPERATOR),
                investigation_only=True,
            )
        )

    monitoring = investigate(CaseIssueType.MISSING_RETURN_REFUND)
    assert not isinstance(monitoring, WorkflowPause)
    assert monitoring.outcome == WorkflowOutcome.WAITING_EXTERNAL
    assert monitoring.verified_resource_id == EXISTING_REFUND_ID
    assert monitoring.operation is None
    proposal = investigate(CaseIssueType.DUPLICATE_CHARGE)
    assert isinstance(proposal, WorkflowPause)
    assert proposal.approval.payment_id == "PAY-COMBINED-2"
    assert proposal.approval.amount == Decimal("150.00")
    with factory() as session:
        assert (
            len(
                list(session.scalars(select(RefundRecord).where(RefundRecord.order_id == ORDER_ID)))
            )
            == 1
        )

    submitted = workflow.resume(
        WorkflowApprovalDecision(
            approval_id=proposal.approval.approval_id,
            decision=ApprovalDecisionType.APPROVE,
            actor=Actor(actor_id="REVIEWER-COMBINED", role=ActorRole.APPROVER),
            note="Verified same obligation and untouched later capture; keep existing return refund.",
        )
    )
    assert not isinstance(submitted, WorkflowPause)
    assert submitted.outcome == WorkflowOutcome.REFUND_SUBMITTED
    assert submitted.status == WorkflowStatus.WAITING_EXTERNAL
    assert submitted.verified_resource_id is not None
    with factory() as session:
        stored = CustomerOperationsStore(session).get_case(case.case_id)
        assert stored is not None and stored.status == CaseStatus.IN_PROGRESS
        assert all(issue.status == CaseIssueStatus.VERIFYING for issue in stored.issues)
        refunds = list(
            session.scalars(select(RefundRecord).where(RefundRecord.order_id == ORDER_ID))
        )
        assert len(refunds) == 2
        assert {r.amount for r in refunds} == {Decimal("120.00"), Decimal("150.00")}
        assert all(r.status == RefundStatus.PENDING for r in refunds)

    processor = RefundEventProcessor(factory, clock=lambda: NOW + timedelta(minutes=3))
    refund_ids = [EXISTING_REFUND_ID, submitted.verified_resource_id]
    if not return_settles_first:
        refund_ids.reverse()
    for index, refund_id in enumerate(refund_ids, start=1):
        event = RefundStatusChangedEvent.model_validate(
            {
                "event_id": f"EVT-COMBINED-{index}",
                "event_type": "refund.status_changed",
                "source": "payment-simulator",
                "occurred_at": NOW + timedelta(minutes=index),
                "data": {
                    "refund_id": refund_id,
                    "provider_reference": f"PROVIDER-{refund_id}",
                    "status": "completed",
                    "completed_at": NOW + timedelta(minutes=index),
                },
            }
        )
        assert processor.process(event).status == InboundEventStatus.PROCESSED
        assert processor.process(event).idempotent_replay is True
        with factory() as session:
            stored = CustomerOperationsStore(session).get_case(case.case_id)
            assert stored is not None
            if index == 1:
                assert stored.status == CaseStatus.IN_PROGRESS
                assert sum(issue.status == CaseIssueStatus.RESOLVED for issue in stored.issues) == 1
            else:
                assert stored.status == CaseStatus.RESOLVED
                assert all(issue.status == CaseIssueStatus.RESOLVED for issue in stored.issues)
    for execution in (monitoring, submitted):
        assert lifecycle.get_run(execution.workflow_id).status == WorkflowLifecycleStatus.COMPLETED
        refreshed = workflow.get_execution(execution.workflow_id)
        assert not isinstance(refreshed, WorkflowPause)
        assert refreshed.outcome == WorkflowOutcome.REFUND_SETTLED
    with factory() as session:
        store = CustomerOperationsStore(session)
        captured = sum((p.amount for p in store.list_payments(ORDER_ID)), Decimal(0))
        refunds = list(
            session.scalars(select(RefundRecord).where(RefundRecord.order_id == ORDER_ID))
        )
        assert len(refunds) == 2
        settled = sum((r.amount for r in refunds if r.status == RefundStatus.COMPLETED), Decimal(0))
        assert captured - settled == Decimal("30.00")
