import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from decimal import Decimal
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from resolveops.database.action_records import OperationRecord
from resolveops.database.event_records import InboundEventRecord, ResourceEventCursorRecord
from resolveops.database.records import CaseIssueRecord, RefundRecord
from resolveops.database.seed import seed_all
from resolveops.database.session import create_session_factory
from resolveops.database.workflow_records import WorkflowEventRecord
from resolveops.events.models import RefundStatusChangedData, RefundStatusChangedEvent
from resolveops.events.processor import RefundEventProcessor
from resolveops.models.case import CaseIssueStatus, IssueFinding
from resolveops.models.refund import RefundKind, RefundStatus
from resolveops.operations.actions import ActionTools
from resolveops.operations.errors import OperationInProgressError
from resolveops.operations.models import Actor, ActorRole, IssueRefundRequest
from resolveops.workflows.lifecycle import WorkflowLifecycleStore
from resolveops.workflows.models import (
    ApprovalDecisionType,
    ApprovalStatus,
    WorkflowApprovalDecision,
    WorkflowEventType,
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
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    factory = create_session_factory(engine)
    with factory.begin() as session:
        seed_all(session)
    try:
        yield engine, factory
    finally:
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
        resource_ids = [future.result(timeout=15) for future in [executor.submit(submit) for _ in range(2)]]

    completed_ids = {resource_id for resource_id in resource_ids if resource_id != "in_progress"}
    assert len(completed_ids) == 1
    with factory() as session:
        assert session.scalar(
            select(func.count()).select_from(RefundRecord).where(RefundRecord.issue_id == "ISSUE-1001")
        ) == 1
        assert session.scalar(
            select(func.count())
            .select_from(OperationRecord)
            .where(OperationRecord.idempotency_key == request.idempotency_key)
        ) == 1


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
        statuses = [future.result(timeout=15) for future in [executor.submit(submit) for _ in range(2)]]

    assert statuses == [ApprovalStatus.APPROVED, ApprovalStatus.APPROVED]
    with factory() as session:
        assert session.scalar(
            select(func.count())
            .select_from(WorkflowEventRecord)
            .where(
                WorkflowEventRecord.workflow_id == "POSTGRES-APPROVAL-RACE",
                WorkflowEventRecord.event_type == WorkflowEventType.APPROVAL_APPROVED,
            )
        ) == 1


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
        replay_flags = [future.result(timeout=15) for future in [executor.submit(submit) for _ in range(2)]]

    assert sorted(replay_flags) == [False, True]
    with factory() as session:
        assert session.scalar(
            select(func.count())
            .select_from(InboundEventRecord)
            .where(InboundEventRecord.event_id == event.event_id)
        ) == 1
        assert session.scalar(
            select(func.count())
            .select_from(ResourceEventCursorRecord)
            .where(ResourceEventCursorRecord.last_event_id == event.event_id)
        ) == 1
        refund = session.get(RefundRecord, "REF-2001")
        assert refund is not None and refund.status == RefundStatus.PROCESSING
