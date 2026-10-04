import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, delete, func, inspect, select
from sqlalchemy.orm import Session, sessionmaker

from resolveops.agents.models import AgentDomain
from resolveops.api.operations import ComplaintSubmission, clarify_complaint, submit_complaint
from resolveops.database.action_records import OperationRecord
from resolveops.database.event_records import InboundEventRecord, ResourceEventCursorRecord
from resolveops.database.records import CaseIssueRecord, CaseMessageRecord, CaseRecord, RefundRecord
from resolveops.database.seed import seed_all
from resolveops.database.session import create_session_factory
from resolveops.database.workflow_records import WorkflowEventRecord, WorkflowRunRecord
from resolveops.events.models import RefundStatusChangedData, RefundStatusChangedEvent
from resolveops.events.processor import RefundEventProcessor
from resolveops.intake.service import ClarificationRequest
from resolveops.jobs.store import AgentJobStore
from resolveops.models.case import CaseIssueStatus, IssueFinding
from resolveops.models.refund import RefundKind, RefundStatus
from resolveops.operations.actions import ActionTools
from resolveops.operations.errors import OperationInProgressError
from resolveops.operations.models import Actor, ActorRole, IssueRefundRequest
from resolveops.security.models import SecurityPrincipal
from resolveops.workflows.case_state import synchronize_refund_state
from resolveops.workflows.lifecycle import WorkflowLifecycleStore
from resolveops.workflows.models import (
    ApprovalDecisionType,
    ApprovalStatus,
    WorkflowApprovalDecision,
    WorkflowEventType,
    WorkflowOutcome,
    WorkflowRequest,
)

NOW = datetime(2026, 9, 29, 16, 0, tzinfo=UTC)


@pytest.fixture
def postgres_database() -> Iterator[tuple[Engine, sessionmaker[Session]]]:
    database_url = os.getenv("RESOLVEOPS_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("RESOLVEOPS_TEST_DATABASE_URL is not set")
    if not database_url.startswith("postgresql+psycopg://"):
        pytest.fail("PostgreSQL test URL must use the psycopg driver")
    engine = create_engine(database_url)
    if "test" not in (engine.url.database or "").lower():
        pytest.fail("Refusing to change a PostgreSQL database without 'test' in its name")
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    if inspect(engine).has_table("workflow_runs"):
        with engine.begin() as connection:
            connection.execute(delete(WorkflowRunRecord))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    factory = create_session_factory(engine)
    with factory.begin() as session:
        seed_all(session)
    try:
        yield engine, factory
    finally:
        with engine.begin() as connection:
            connection.execute(delete(WorkflowRunRecord))
        engine.dispose()
        command.downgrade(config, "base")


@pytest.mark.postgres
def test_simultaneous_refund_requests_create_one_side_effect(
    postgres_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = postgres_database
    with factory.begin() as session:
        issue = session.get(CaseIssueRecord, "ISSUE-1001")
        assert issue is not None
        issue.finding = IssueFinding.CONFIRMED
        issue.status = CaseIssueStatus.ACTION_PENDING
    request = IssueRefundRequest(
        idempotency_key="postgres-concurrent-refund",
        case_id="CASE-1001",
        issue_id="ISSUE-1001",
        payment_id="PAY-1002",
        amount=Decimal("1499.00"),
        currency="USD",
        kind=RefundKind.DUPLICATE_CHARGE,
        reason="Concurrent PostgreSQL refund proof",
    )
    actor = Actor(actor_id="POSTGRES-APPROVER", role=ActorRole.APPROVER)
    barrier = Barrier(2)

    def submit() -> str:
        barrier.wait(timeout=5)
        try:
            return ActionTools(factory).issue_refund(request, actor).resource_id
        except OperationInProgressError:
            return "in_progress"

    with ThreadPoolExecutor(max_workers=2) as executor:
        resource_ids = [
            future.result(timeout=15) for future in [executor.submit(submit) for _ in range(2)]
        ]

    completed_ids = {resource_id for resource_id in resource_ids if resource_id != "in_progress"}
    assert len(completed_ids) == 1
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(RefundRecord)
                .where(RefundRecord.issue_id == "ISSUE-1001")
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(OperationRecord)
                .where(OperationRecord.idempotency_key == request.idempotency_key)
            )
            == 1
        )


@pytest.mark.postgres
def test_two_workers_cannot_claim_the_same_agent_job(
    postgres_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = postgres_database
    store = AgentJobStore(factory)
    queued = store.enqueue(
        tenant_id="TENANT-TEST",
        workflow_id="WF-CONCURRENT-AGENT",
        case_id="CASE-1001",
        domain=AgentDomain.CUSTOMER_OPERATIONS,
        objective="Prove that only one worker owns the job.",
        idempotency_key="CONCURRENT-AGENT-KEY",
    )
    barrier = Barrier(2)

    def claim(worker_id: str) -> str | None:
        barrier.wait(timeout=5)
        claimed = store.claim_next(worker_id)
        return None if claimed is None else claimed.job_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = [
            future.result(timeout=15)
            for future in [
                executor.submit(claim, "WORKER-A"),
                executor.submit(claim, "WORKER-B"),
            ]
        ]

    assert claims.count(queued.job_id) == 1
    assert claims.count(None) == 1


@pytest.mark.postgres
def test_duplicate_approval_submissions_create_one_decision_event(
    postgres_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = postgres_database
    operator = Actor(actor_id="POSTGRES-OPERATOR", role=ActorRole.OPERATOR)
    approver = Actor(actor_id="POSTGRES-APPROVER", role=ActorRole.APPROVER)
    refund_request = IssueRefundRequest(
        idempotency_key="postgres-approval-refund",
        case_id="CASE-1001",
        issue_id="ISSUE-1001",
        payment_id="PAY-1002",
        amount=Decimal("1499.00"),
        currency="USD",
        kind=RefundKind.DUPLICATE_CHARGE,
        reason="PostgreSQL approval race proof",
    )
    lifecycle = WorkflowLifecycleStore(factory)
    lifecycle.start(
        WorkflowRequest(
            workflow_id="POSTGRES-APPROVAL-RACE",
            case_id="CASE-1001",
            issue_id="ISSUE-1001",
            actor=operator,
            refund_request=refund_request,
        )
    )
    approval = lifecycle.request_refund_approval(
        workflow_id="POSTGRES-APPROVAL-RACE",
        request=refund_request,
        requested_by=operator.actor_id,
        requested_role=operator.role,
        reason="Operator limit requires approval.",
    )
    decision = WorkflowApprovalDecision(
        approval_id=approval.approval_id,
        decision=ApprovalDecisionType.APPROVE,
        actor=approver,
        note="Concurrent approval decision with identical payload.",
    )
    barrier = Barrier(2)

    def submit() -> ApprovalStatus:
        barrier.wait(timeout=5)
        return WorkflowLifecycleStore(factory).decide_approval(decision).status

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = [
            future.result(timeout=15) for future in [executor.submit(submit) for _ in range(2)]
        ]

    assert statuses == [ApprovalStatus.APPROVED, ApprovalStatus.APPROVED]
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkflowEventRecord)
                .where(
                    WorkflowEventRecord.workflow_id == "POSTGRES-APPROVAL-RACE",
                    WorkflowEventRecord.event_type == WorkflowEventType.APPROVAL_APPROVED,
                )
            )
            == 1
        )


@pytest.mark.postgres
def test_duplicate_webhook_delivery_creates_one_receipt_and_transition(
    postgres_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = postgres_database
    event = RefundStatusChangedEvent(
        event_id="POSTGRES-CONCURRENT-EVENT",
        source="postgres-concurrency-test",
        occurred_at=NOW,
        data=RefundStatusChangedData(
            refund_id="REF-2001",
            provider_reference="POSTGRES-CONCURRENT-REF",
            status=RefundStatus.PROCESSING,
        ),
    )
    barrier = Barrier(2)

    def submit() -> bool:
        barrier.wait(timeout=5)
        return RefundEventProcessor(factory, clock=lambda: NOW).process(event).idempotent_replay

    with ThreadPoolExecutor(max_workers=2) as executor:
        replay_flags = [
            future.result(timeout=15) for future in [executor.submit(submit) for _ in range(2)]
        ]

    assert sorted(replay_flags) == [False, True]
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(InboundEventRecord)
                .where(InboundEventRecord.event_id == event.event_id)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ResourceEventCursorRecord)
                .where(ResourceEventCursorRecord.last_event_id == event.event_id)
            )
            == 1
        )
        refund = session.get(RefundRecord, "REF-2001")
        assert refund is not None and refund.status == RefundStatus.PROCESSING


@pytest.mark.postgres
def test_concurrent_intake_reuses_one_case_and_message_receipt(
    postgres_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = postgres_database
    principal = SecurityPrincipal(
        subject_id="POSTGRES-OPERATOR", tenant_id="TENANT-TEST", role=ActorRole.OPERATOR
    )
    body = ComplaintSubmission(
        customer_id="CUST-1001",
        order_id="ORD-48391",
        complaint="I was charged twice.",
        source_message_id="POSTGRES-INTAKE-RACE",
    )
    barrier = Barrier(2)

    def submit() -> str:
        with factory() as session:
            barrier.wait(timeout=5)
            return submit_complaint(body, session, principal).case_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit) for _ in range(2)]
        case_ids = [future.result(timeout=15) for future in futures]

    assert len(set(case_ids)) == 1
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(CaseMessageRecord)
                .where(
                    CaseMessageRecord.case_id == case_ids[0],
                    CaseMessageRecord.source_message_id == body.source_message_id,
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(CaseIssueRecord)
                .where(
                    CaseIssueRecord.case_id == case_ids[0],
                )
            )
            == 1
        )


@pytest.mark.postgres
def test_concurrent_identical_clarification_is_appended_once(
    postgres_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = postgres_database
    principal = SecurityPrincipal(
        subject_id="POSTGRES-OPERATOR", tenant_id="TENANT-TEST", role=ActorRole.OPERATOR
    )
    with factory() as session:
        case = submit_complaint(
            ComplaintSubmission(
                customer_id="CUST-1001",
                order_id="ORD-48391",
                complaint="Something is wrong with my order.",
                source_message_id="PG-AMBIGUOUS",
            ),
            session,
            principal,
        )
    assert case.issues == []
    body = ClarificationRequest(
        source_message_id="POSTGRES-REPLY-RACE",
        message="I returned my item but the refund is missing.",
        return_id="RET-3001",
    )
    barrier = Barrier(2)

    def clarify() -> str:
        with factory() as session:
            barrier.wait(timeout=5)
            return clarify_complaint(case.case_id, body, session, principal).case_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(clarify) for _ in range(2)]
        assert [future.result(timeout=15) for future in futures] == [case.case_id, case.case_id]
    with factory() as session:
        stored = session.get(CaseRecord, case.case_id)
        assert stored is not None and stored.complaint_text is not None
        assert stored.complaint_text.count(body.message) == 1
        assert (
            session.scalar(
                select(func.count())
                .select_from(CaseMessageRecord)
                .where(
                    CaseMessageRecord.case_id == case.case_id,
                    CaseMessageRecord.source_message_id == body.source_message_id,
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(CaseIssueRecord)
                .where(
                    CaseIssueRecord.case_id == case.case_id,
                )
            )
            == 1
        )


@pytest.mark.postgres
def test_simultaneous_refund_portion_events_leave_one_consistent_resolved_issue(
    postgres_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = postgres_database
    with factory.begin() as session:
        original = session.get(RefundRecord, "REF-2001")
        assert original is not None
        original.amount = Decimal("100.00")
        session.add(
            RefundRecord(
                refund_id="REF-PG-PORTION-2",
                payment_id=original.payment_id,
                order_id=original.order_id,
                issue_id=original.issue_id,
                return_id=original.return_id,
                amount=Decimal("100.00"),
                currency=original.currency,
                status=RefundStatus.PENDING,
                kind=original.kind,
                reason="Second portion of the received return",
                created_at=NOW - timedelta(minutes=1),
                completed_at=None,
            )
        )
    barrier = Barrier(2)

    def settle(refund_id: str) -> str:
        barrier.wait(timeout=5)
        receipt = RefundEventProcessor(factory, clock=lambda: NOW).process(
            RefundStatusChangedEvent(
                event_id=f"EVT-{refund_id}",
                source="postgres-concurrency-test",
                occurred_at=NOW,
                data=RefundStatusChangedData(
                    refund_id=refund_id,
                    provider_reference=f"PROVIDER-{refund_id}",
                    status="completed",
                    completed_at=NOW,
                ),
            )
        )
        return receipt.status.value

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(settle, refund_id) for refund_id in ("REF-2001", "REF-PG-PORTION-2")
        ]
        assert [future.result(timeout=15) for future in futures] == ["processed", "processed"]
    with factory() as session:
        issue = session.get(CaseIssueRecord, "ISSUE-1002")
        assert issue is not None and issue.status == CaseIssueStatus.RESOLVED
        refunds = list(
            session.scalars(select(RefundRecord).where(RefundRecord.return_id == "RET-3001"))
        )
        assert len(refunds) == 2
        assert all(refund.status == RefundStatus.COMPLETED for refund in refunds)


@pytest.mark.postgres
def test_stale_identity_map_cannot_reopen_settled_refund(
    postgres_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = postgres_database
    with factory() as stale_session:
        stale_refund = stale_session.get(RefundRecord, "REF-2001")
        assert stale_refund is not None and stale_refund.status == RefundStatus.PENDING
        RefundEventProcessor(factory, clock=lambda: NOW).process(
            RefundStatusChangedEvent(
                event_id="EVT-PG-SETTLED",
                source="postgres-concurrency-test",
                occurred_at=NOW,
                data=RefundStatusChangedData(
                    refund_id="REF-2001",
                    provider_reference="PROVIDER-PG-SETTLED",
                    status="completed",
                    completed_at=NOW,
                ),
            )
        )
        assert stale_refund.status == RefundStatus.PENDING
        projection = synchronize_refund_state(stale_session, stale_refund, NOW)
        stale_session.commit()
        assert projection.outcome == WorkflowOutcome.REFUND_SETTLED
    with factory() as session:
        issue = session.get(CaseIssueRecord, "ISSUE-1002")
        assert issue is not None and issue.status == CaseIssueStatus.RESOLVED
