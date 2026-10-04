"""Business-level regressions start at intake and do not pre-confirm the finding."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine, func, select

from resolveops.database.base import Base
from resolveops.database.records import PaymentRecord, RefundRecord
from resolveops.database.seed import seed_all
from resolveops.database.session import create_session_factory
from resolveops.intake.service import CaseIntakeService, ClarificationRequest, IntakeRequest
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.knowledge.ingestion import ingest_directory
from resolveops.models.case import CaseIssueStatus, CaseStatus
from resolveops.operations.models import Actor, ActorRole
from resolveops.workflows.customer_issue import CustomerIssueWorkflow
from resolveops.workflows.lifecycle import WorkflowLifecycleStore
from resolveops.workflows.models import (
    ApprovalDecisionType,
    WorkflowApprovalDecision,
    WorkflowOutcome,
    WorkflowPause,
    WorkflowRequest,
)

NOW = datetime(2026, 10, 4, tzinfo=UTC)


@pytest.fixture
def journey():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    embeddings = FeatureHashEmbeddingProvider(dimensions=128)
    with factory.begin() as session:
        seed_all(session)
        ingest_directory(
            session, Path("domain_packs/customer_operations/policies"), embeddings, ingested_at=NOW
        )
    clock = [NOW]
    workflow = CustomerIssueWorkflow(
        factory,
        embeddings,
        checkpointer=InMemorySaver(),
        lifecycle_store=WorkflowLifecycleStore(factory, clock=lambda: clock[0]),
        clock=lambda: clock[0],
    )
    yield factory, workflow, clock
    engine.dispose()


def new_complaint(factory, workflow, text="I was charged twice.", order="A"):
    with factory.begin() as session:
        case, _ = CaseIntakeService(session, clock=lambda: NOW).submit(
            IntakeRequest(
                customer_id=f"CUST-DEMO-{order}",
                order_id=f"ORD-DEMO-{order}",
                complaint=text,
                source_message_id="fresh-intake",
            )
        )
    return case, workflow.start(
        WorkflowRequest(
            workflow_id=f"RUN-{case.case_id}",
            case_id=case.case_id,
            issue_id=case.issues[0].issue_id,
            actor=Actor(actor_id="OPERATOR", role=ActorRole.OPERATOR),
            investigation_only=True,
        )
    )


def approve(workflow, pause):
    assert isinstance(pause, WorkflowPause)
    return workflow.resume(
        WorkflowApprovalDecision(
            approval_id=pause.approval.approval_id,
            decision=ApprovalDecisionType.APPROVE,
            actor=Actor(actor_id="REVIEWER", role=ActorRole.APPROVER),
            note="I checked the evidence and exact target capture.",
        )
    )


def test_new_intake_proposes_without_mutation_then_pending_after_approval(journey):
    factory, workflow, _ = journey
    case, pause = new_complaint(factory, workflow)
    assert isinstance(pause, WorkflowPause)
    assert pause.approval.payment_id == "PAY-DEMO-A-2"
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(RefundRecord)
                .where(RefundRecord.order_id == case.order_id)
            )
            == 0
        )
    result = approve(workflow, pause)
    assert result.outcome == WorkflowOutcome.REFUND_SUBMITTED
    with factory() as session:
        stored = CaseIntakeService(session).store.get_case(case.case_id)
        assert stored.status != CaseStatus.RESOLVED
        assert stored.issues[0].status == CaseIssueStatus.VERIFYING


def test_return_intake_derives_amount_and_capture_without_client_proposal(journey):
    factory, workflow, _ = journey
    _, pause = new_complaint(
        factory, workflow, "I returned my item but the refund is missing.", "B"
    )
    assert isinstance(pause, WorkflowPause)
    assert pause.approval.payment_id == "PAY-DEMO-B-1"
    assert pause.approval.amount == Decimal("120.00")


def test_changed_payment_evidence_invalidates_approval(journey):
    factory, workflow, _ = journey
    _, pause = new_complaint(factory, workflow)
    with factory.begin() as session:
        session.get(PaymentRecord, "PAY-DEMO-A-2").obligation_id = "DIFFERENT-OBLIGATION"
    result = approve(workflow, pause)
    assert result.error_code == "approval_evidence_changed"
    assert result.operation is None


def test_expired_proposal_cannot_move_money(journey):
    factory, workflow, clock = journey
    _, pause = new_complaint(factory, workflow)
    clock[0] += timedelta(minutes=31)
    result = approve(workflow, pause)
    assert result.error_code == "approval_expired"
    assert result.operation is None


def test_repeated_new_case_monitors_refund_from_previous_case(journey):
    factory, workflow, _ = journey
    _, pause = new_complaint(factory, workflow)
    first = approve(workflow, pause)
    with factory.begin() as session:
        case, _ = CaseIntakeService(session, clock=lambda: NOW).submit(
            IntakeRequest(
                customer_id="CUST-DEMO-A",
                order_id="ORD-DEMO-A",
                complaint="Two charges still appear.",
                source_message_id="second-customer-message",
            )
        )
    followup = workflow.start(
        WorkflowRequest(
            workflow_id="FOLLOWUP",
            case_id=case.case_id,
            issue_id=case.issues[0].issue_id,
            actor=Actor(actor_id="OPERATOR", role=ActorRole.OPERATOR),
            investigation_only=True,
        )
    )
    assert followup.outcome == WorkflowOutcome.WAITING_EXTERNAL
    assert followup.verified_resource_id == first.verified_resource_id
    assert followup.operation is None


def test_ambiguous_complaint_can_continue_in_same_case(journey):
    factory, workflow, _ = journey
    with factory.begin() as session:
        service = CaseIntakeService(session, clock=lambda: NOW)
        intake = IntakeRequest(
            customer_id="CUST-DEMO-B",
            order_id="ORD-DEMO-B",
            complaint="Something is wrong with my payment.",
            source_message_id="ambiguous",
        )
        case, _ = service.submit(intake)
        assert case.issues == []
        duplicate, _ = service.submit(intake)
        assert duplicate.case_id == case.case_id
        reply = ClarificationRequest(
            source_message_id="reply-1",
            message="I returned my item but my refund is missing.",
            return_id="RET-DEMO-B",
        )
        clarified = service.clarify(case.case_id, reply)
        assert clarified.case_id == case.case_id
        assert len(clarified.issues) == 1
        assert service.clarify(case.case_id, reply) == clarified
        with pytest.raises(ValueError, match="different content"):
            service.clarify(case.case_id, reply.model_copy(update={"return_id": None}))
    outcome = workflow.start(
        WorkflowRequest(
            workflow_id="CLARIFIED",
            case_id=clarified.case_id,
            issue_id=clarified.issues[0].issue_id,
            actor=Actor(actor_id="OPERATOR", role=ActorRole.OPERATOR),
            investigation_only=True,
        )
    )
    assert isinstance(outcome, WorkflowPause)
    assert outcome.approval.amount == Decimal("120.00")


def test_intake_receipt_cannot_be_reused_with_changed_text(journey):
    factory, _, _ = journey
    with factory.begin() as session:
        service = CaseIntakeService(session, clock=lambda: NOW)
        request = IntakeRequest(
            customer_id="CUST-DEMO-A",
            order_id="ORD-DEMO-A",
            complaint="I was charged twice.",
            source_message_id="same-message",
        )
        service.submit(request)
        with pytest.raises(ValueError, match="different content"):
            service.submit(request.model_copy(update={"complaint": "Different request"}))
