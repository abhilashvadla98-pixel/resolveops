from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event

import pytest
from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from resolveops.database.action_records import AuditEventRecord, OperationRecord
from resolveops.database.base import Base
from resolveops.database.records import (
    CaseIssuePaymentRecord,
    CaseIssueRecord,
    RefundRecord,
)
from resolveops.database.seed import seed_all
from resolveops.database.session import create_session_factory
from resolveops.database.simulator_records import NotificationRecord, TicketRecord
from resolveops.models.case import CaseIssueStatus, IssueFinding
from resolveops.models.notification import NotificationChannel
from resolveops.models.refund import RefundKind
from resolveops.operations.actions import ActionTools
from resolveops.operations.errors import (
    ApprovalRequiredError,
    AuthorizationError,
    BusinessRuleError,
    IdempotencyConflictError,
    OperationInProgressError,
    RecoveryRequiredError,
    ResourceNotFoundError,
    RetryExhaustedError,
    TransientOperationError,
    VerificationError,
)
from resolveops.operations.models import (
    Actor,
    ActorRole,
    AuditEventType,
    CompensationStrategy,
    CreateTicketRequest,
    IssueRefundRequest,
    OperationStatus,
    OperationType,
    RecoveryDisposition,
    ReliabilityEventType,
    SendNotificationRequest,
)
from resolveops.operations.reads import OperationsReadTools
from resolveops.operations.reliability import ReliabilityPolicy

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def sqlite_engine() -> Engine:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def operation_database() -> tuple[Engine, sessionmaker[Session]]:
    engine = sqlite_engine()
    factory = create_session_factory(engine)
    with factory.begin() as session:
        seed_all(session)
    yield engine, factory
    engine.dispose()


@pytest.fixture
def ids() -> Callable[[str], str]:
    sequence = iter(range(1, 100))
    return lambda prefix: f"{prefix}-{next(sequence):04d}"


def action_tools(factory: sessionmaker[Session], ids: Callable[[str], str]) -> ActionTools:
    return ActionTools(factory, clock=lambda: NOW, id_generator=ids)


def actor(role: ActorRole) -> Actor:
    return Actor(actor_id=f"USER-{role.value.upper()}", role=role)


def duplicate_refund_request(
    *, key: str = "refund-key-1", reason: str = "Confirmed duplicate charge"
) -> IssueRefundRequest:
    return IssueRefundRequest(
        idempotency_key=key,
        case_id="CASE-1001",
        issue_id="ISSUE-1001",
        payment_id="PAY-1002",
        amount=Decimal("1499.00"),
        currency="USD",
        kind=RefundKind.DUPLICATE_CHARGE,
        reason=reason,
    )


def make_duplicate_issue_actionable(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        issue = session.get(CaseIssueRecord, "ISSUE-1001")
        assert issue is not None
        issue.finding = IssueFinding.CONFIRMED
        issue.status = CaseIssueStatus.ACTION_PENDING


def test_read_tools_return_typed_resources_and_explicit_not_found(
    operation_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = operation_database
    with factory() as session:
        reads = OperationsReadTools(session, actor(ActorRole.AGENT))
        assert reads.get_customer("CUST-1001").name == "M*** P***"
        assert (
            OperationsReadTools(session, actor(ActorRole.OPERATOR)).get_customer("CUST-1001").name
            == "Maya Patel"
        )
        assert reads.get_payment("PAY-1002").amount == Decimal("1499.00")
        assert reads.get_case("CASE-1001").issues[0].issue_id == "ISSUE-1001"
        with pytest.raises(ResourceNotFoundError, match="does not exist"):
            reads.get_order("ORD-MISSING")


def test_agent_cannot_issue_refund_and_denial_is_audited(
    operation_database: tuple[Engine, sessionmaker[Session]],
    ids: Callable[[str], str],
) -> None:
    _, factory = operation_database
    tools = action_tools(factory, ids)

    with pytest.raises(AuthorizationError) as error:
        tools.issue_refund(duplicate_refund_request(), actor(ActorRole.AGENT))
    assert error.value.code == "permission_denied"

    with factory() as session:
        operation = session.scalar(select(OperationRecord))
        assert operation is not None
        assert operation.status == OperationStatus.FAILED
        assert operation.error_code == "permission_denied"
        events = list(
            session.scalars(select(AuditEventRecord).order_by(AuditEventRecord.sequence_number))
        )
        assert [event.event_type for event in events] == [
            AuditEventType.REQUESTED,
            AuditEventType.DENIED,
        ]


def test_operator_limit_requires_higher_approval(
    operation_database: tuple[Engine, sessionmaker[Session]],
    ids: Callable[[str], str],
) -> None:
    _, factory = operation_database
    with pytest.raises(ApprovalRequiredError) as error:
        action_tools(factory, ids).issue_refund(
            duplicate_refund_request(), actor(ActorRole.OPERATOR)
        )
    assert error.value.code == "refund_approval_required"


def test_approver_refund_is_verified_audited_and_idempotent(
    operation_database: tuple[Engine, sessionmaker[Session]],
    ids: Callable[[str], str],
) -> None:
    _, factory = operation_database
    make_duplicate_issue_actionable(factory)
    tools = action_tools(factory, ids)
    request = duplicate_refund_request()

    first = tools.issue_refund(request, actor(ActorRole.APPROVER))
    second = tools.issue_refund(request, actor(ActorRole.APPROVER))

    assert first.verified is True and first.idempotent_replay is False
    assert second.resource_id == first.resource_id
    assert second.operation_id == first.operation_id
    assert second.idempotent_replay is True
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(RefundRecord)
                .where(RefundRecord.issue_id == "ISSUE-1001")
            )
            == 1
        )
        reads = OperationsReadTools(session, actor(ActorRole.AGENT))
        events = reads.list_operation_audit(first.operation_id)
        assert [event.event_type for event in events] == [
            AuditEventType.REQUESTED,
            AuditEventType.AUTHORIZED,
            AuditEventType.EXECUTED,
            AuditEventType.VERIFIED,
        ]


def test_same_idempotency_key_rejects_changed_payload(
    operation_database: tuple[Engine, sessionmaker[Session]],
    ids: Callable[[str], str],
) -> None:
    _, factory = operation_database
    make_duplicate_issue_actionable(factory)
    tools = action_tools(factory, ids)
    approver = actor(ActorRole.APPROVER)
    tools.issue_refund(duplicate_refund_request(), approver)

    with pytest.raises(IdempotencyConflictError):
        tools.issue_refund(duplicate_refund_request(reason="A different reason"), approver)


def test_duplicate_refund_requires_two_matching_captured_payments(
    operation_database: tuple[Engine, sessionmaker[Session]],
    ids: Callable[[str], str],
) -> None:
    _, factory = operation_database
    make_duplicate_issue_actionable(factory)
    with factory.begin() as session:
        link = session.get(CaseIssuePaymentRecord, ("ISSUE-1001", "PAY-1001"))
        assert link is not None
        session.delete(link)

    with pytest.raises(BusinessRuleError) as error:
        action_tools(factory, ids).issue_refund(
            duplicate_refund_request(), actor(ActorRole.APPROVER)
        )
    assert error.value.code == "duplicate_evidence_missing"


def test_existing_pending_return_refund_blocks_over_refund(
    operation_database: tuple[Engine, sessionmaker[Session]],
    ids: Callable[[str], str],
) -> None:
    _, factory = operation_database
    with factory.begin() as session:
        issue = session.get(CaseIssueRecord, "ISSUE-1002")
        assert issue is not None
        issue.finding = IssueFinding.CONFIRMED
        issue.status = CaseIssueStatus.ACTION_PENDING
    request = IssueRefundRequest(
        idempotency_key="return-refund-key",
        case_id="CASE-1001",
        issue_id="ISSUE-1002",
        payment_id="PAY-1001",
        return_id="RET-3001",
        amount=Decimal("1.00"),
        currency="USD",
        kind=RefundKind.RETURN,
        reason="Additional return refund",
    )

    with pytest.raises(BusinessRuleError) as error:
        action_tools(factory, ids).issue_refund(request, actor(ActorRole.APPROVER))
    assert error.value.code == "return_refund_limit_exceeded"


def test_notification_and_ticket_actions_validate_and_replay(
    operation_database: tuple[Engine, sessionmaker[Session]],
    ids: Callable[[str], str],
) -> None:
    _, factory = operation_database
    tools = action_tools(factory, ids)
    agent = actor(ActorRole.AGENT)
    notification_request = SendNotificationRequest(
        idempotency_key="notification-key",
        case_id="CASE-1001",
        customer_id="CUST-1001",
        channel=NotificationChannel.EMAIL,
        recipient="maya.patel@example.com",
        message="We confirmed your request and are working on it.",
    )
    ticket_request = CreateTicketRequest(
        idempotency_key="ticket-key",
        case_id="CASE-1001",
        subject="Follow up with payment provider",
        description="Confirm the duplicate capture reference with the provider.",
    )

    notification = tools.send_notification(notification_request, agent)
    replay = tools.send_notification(notification_request, agent)
    ticket = tools.create_ticket(ticket_request, agent)

    assert replay.resource_id == notification.resource_id
    assert replay.idempotent_replay is True
    with factory() as session:
        assert session.get(NotificationRecord, notification.resource_id) is not None
        assert session.get(TicketRecord, ticket.resource_id) is not None


def test_notification_rejects_unverified_recipient(
    operation_database: tuple[Engine, sessionmaker[Session]],
    ids: Callable[[str], str],
) -> None:
    _, factory = operation_database
    request = SendNotificationRequest(
        idempotency_key="wrong-recipient-key",
        case_id="CASE-1001",
        customer_id="CUST-1001",
        channel=NotificationChannel.EMAIL,
        recipient="attacker@example.com",
        message="Sensitive case update",
    )
    with pytest.raises(BusinessRuleError) as error:
        action_tools(factory, ids).send_notification(request, actor(ActorRole.AGENT))
    assert error.value.code == "recipient_mismatch"


def test_failed_fresh_read_marks_verification_failure(
    operation_database: tuple[Engine, sessionmaker[Session]],
    ids: Callable[[str], str],
) -> None:
    _, factory = operation_database

    class FailingVerificationTools(ActionTools):
        @staticmethod
        def _verify_ticket(session: Session, ticket_id: str, request: CreateTicketRequest) -> bool:
            return False

    tools = FailingVerificationTools(factory, clock=lambda: NOW, id_generator=ids)
    request = CreateTicketRequest(
        idempotency_key="failed-verification-key",
        case_id="CASE-1001",
        subject="Verify this ticket",
        description="Exercise the independent verification failure path.",
    )
    with pytest.raises(VerificationError):
        tools.create_ticket(request, actor(ActorRole.AGENT))

    with factory() as session:
        operation = session.scalar(
            select(OperationRecord).where(
                OperationRecord.idempotency_key == "failed-verification-key"
            )
        )
        assert operation is not None
        assert operation.status == OperationStatus.VERIFICATION_FAILED
        event_types = list(
            session.scalars(
                select(AuditEventRecord.event_type)
                .where(AuditEventRecord.operation_id == operation.operation_id)
                .order_by(AuditEventRecord.sequence_number)
            )
        )
        assert event_types[-1] == AuditEventType.VERIFICATION_FAILED


def test_transient_failure_retries_with_bounded_backoff(
    operation_database: tuple[Engine, sessionmaker[Session]],
    ids: Callable[[str], str],
) -> None:
    _, factory = operation_database

    class TransientTicketTools(ActionTools):
        execution_calls = 0

        def _execute_ticket(
            self, session: Session, ticket_id: str, request: CreateTicketRequest
        ) -> None:
            self.execution_calls += 1
            if self.execution_calls < 3:
                raise TransientOperationError(
                    "provider_temporarily_unavailable",
                    "the ticket provider is temporarily unavailable",
                )
            super()._execute_ticket(session, ticket_id, request)

    delays: list[float] = []
    tools = TransientTicketTools(
        factory,
        clock=lambda: NOW,
        id_generator=ids,
        reliability_policy=ReliabilityPolicy(
            max_attempts=3,
            initial_backoff_seconds=0.25,
            backoff_multiplier=2,
            max_backoff_seconds=1,
        ),
        sleeper=delays.append,
    )
    request = CreateTicketRequest(
        idempotency_key="transient-ticket-key",
        case_id="CASE-1001",
        subject="Retry provider request",
        description="Exercise bounded transient retries.",
    )

    result = tools.create_ticket(request, actor(ActorRole.AGENT))

    assert result.verified is True
    assert tools.execution_calls == 3
    assert delays == [0.25, 0.5]
    with factory() as session:
        operation = session.get(OperationRecord, result.operation_id)
        assert operation is not None
        assert operation.attempt_count == 3
        assert operation.status == OperationStatus.COMPLETED
    assert [event.event_type for event in tools.list_reliability_events(result.operation_id)] == [
        ReliabilityEventType.ATTEMPT_STARTED,
        ReliabilityEventType.RETRY_SCHEDULED,
        ReliabilityEventType.ATTEMPT_STARTED,
        ReliabilityEventType.RETRY_SCHEDULED,
        ReliabilityEventType.ATTEMPT_STARTED,
        ReliabilityEventType.ATTEMPT_SUCCEEDED,
        ReliabilityEventType.VERIFICATION_ATTEMPTED,
    ]


def test_timeout_rolls_back_before_retrying_same_action(
    operation_database: tuple[Engine, sessionmaker[Session]],
    ids: Callable[[str], str],
) -> None:
    _, factory = operation_database
    monotonic_values = iter([0.0, 2.0, 3.0, 3.1])
    delays: list[float] = []
    tools = ActionTools(
        factory,
        clock=lambda: NOW,
        id_generator=ids,
        reliability_policy=ReliabilityPolicy(
            max_attempts=2,
            initial_backoff_seconds=0,
            attempt_timeout_seconds=1,
        ),
        sleeper=delays.append,
        monotonic_clock=lambda: next(monotonic_values),
    )
    request = CreateTicketRequest(
        idempotency_key="timeout-ticket-key",
        case_id="CASE-1001",
        subject="Transaction deadline",
        description="The first transaction must roll back before retry.",
    )

    result = tools.create_ticket(request, actor(ActorRole.AGENT))

    assert result.verified is True
    assert delays == [0]
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(TicketRecord)
                .where(TicketRecord.subject == request.subject)
            )
            == 1
        )
        operation = session.get(OperationRecord, result.operation_id)
        assert operation is not None and operation.attempt_count == 2
    retry_event = next(
        event
        for event in tools.list_reliability_events(result.operation_id)
        if event.event_type == ReliabilityEventType.RETRY_SCHEDULED
    )
    assert retry_event.details["error_code"] == "operation_attempt_timed_out"
    assert retry_event.details["compensation"] == "transaction_rollback"


def test_verification_failure_never_reexecutes_and_supports_verify_only_recovery(
    operation_database: tuple[Engine, sessionmaker[Session]],
    ids: Callable[[str], str],
) -> None:
    _, factory = operation_database

    class EventuallyVisibleTicketTools(ActionTools):
        execution_calls = 0
        verification_calls = 0

        def _execute_ticket(
            self, session: Session, ticket_id: str, request: CreateTicketRequest
        ) -> None:
            self.execution_calls += 1
            super()._execute_ticket(session, ticket_id, request)

        def _verify_ticket(
            self, session: Session, ticket_id: str, request: CreateTicketRequest
        ) -> bool:
            self.verification_calls += 1
            if self.verification_calls <= 3:
                return False
            return super()._verify_ticket(session, ticket_id, request)

    tools = EventuallyVisibleTicketTools(
        factory,
        clock=lambda: NOW,
        id_generator=ids,
        reliability_policy=ReliabilityPolicy(max_attempts=3, initial_backoff_seconds=0),
        sleeper=lambda _: None,
    )
    request = CreateTicketRequest(
        idempotency_key="verification-recovery-key",
        case_id="CASE-1001",
        subject="Verify without duplicate execution",
        description="Recover only by reading the committed result.",
    )
    agent = actor(ActorRole.AGENT)

    with pytest.raises(VerificationError):
        tools.create_ticket(request, agent)
    with pytest.raises(RecoveryRequiredError):
        tools.create_ticket(request, agent)

    plan = tools.get_recovery_plan(request.idempotency_key)
    assert plan.disposition == RecoveryDisposition.VERIFY_ONLY
    assert plan.compensation == CompensationStrategy.MANUAL
    assert plan.safe_to_retry is False

    recovered = tools.recover_ticket(request, agent)

    assert recovered.verified is True
    assert recovered.idempotent_replay is True
    assert tools.execution_calls == 1
    assert tools.verification_calls == 4
    assert tools.get_recovery_plan(request.idempotency_key).disposition == (
        RecoveryDisposition.COMPLETE
    )


def test_retry_exhaustion_records_manual_recovery_without_side_effect(
    operation_database: tuple[Engine, sessionmaker[Session]],
    ids: Callable[[str], str],
) -> None:
    _, factory = operation_database

    class UnavailableTicketTools(ActionTools):
        def _execute_ticket(
            self, session: Session, ticket_id: str, request: CreateTicketRequest
        ) -> None:
            raise TransientOperationError(
                "provider_temporarily_unavailable",
                "the provider remained unavailable",
            )

    tools = UnavailableTicketTools(
        factory,
        clock=lambda: NOW,
        id_generator=ids,
        reliability_policy=ReliabilityPolicy(max_attempts=2, initial_backoff_seconds=0),
        sleeper=lambda _: None,
    )
    request = CreateTicketRequest(
        idempotency_key="retry-exhausted-key",
        case_id="CASE-1001",
        subject="Unavailable provider",
        description="Stop after the bounded attempt count.",
    )

    with pytest.raises(RetryExhaustedError):
        tools.create_ticket(request, actor(ActorRole.AGENT))

    plan = tools.get_recovery_plan(request.idempotency_key)
    assert plan.status == OperationStatus.FAILED
    assert plan.disposition == RecoveryDisposition.MANUAL_REVIEW
    assert plan.compensation == CompensationStrategy.TRANSACTION_ROLLBACK
    assert plan.attempt_count == 2
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(TicketRecord)
                .where(TicketRecord.subject == request.subject)
            )
            == 0
        )


def test_expired_started_operation_is_recovered_with_same_idempotency_key(
    operation_database: tuple[Engine, sessionmaker[Session]],
    ids: Callable[[str], str],
) -> None:
    _, factory = operation_database
    request = CreateTicketRequest(
        idempotency_key="expired-lease-key",
        case_id="CASE-1001",
        subject="Recover expired operation",
        description="Continue a crash-safe started operation.",
    )
    agent = actor(ActorRole.AGENT)
    with factory.begin() as session:
        session.add(
            OperationRecord(
                operation_id="OP-EXPIRED",
                idempotency_key=request.idempotency_key,
                operation_type=OperationType.CREATE_TICKET,
                payload_hash=ActionTools._payload_hash(OperationType.CREATE_TICKET, request),
                status=OperationStatus.STARTED,
                actor_id=agent.actor_id,
                actor_role=agent.role,
                case_id=request.case_id,
                issue_id=None,
                result_resource_id=None,
                error_code=None,
                error_message=None,
                attempt_count=0,
                verification_attempt_count=0,
                max_attempts=3,
                last_error_retryable=False,
                last_attempt_at=None,
                next_attempt_at=None,
                lease_expires_at=NOW - timedelta(seconds=1),
                created_at=NOW - timedelta(minutes=1),
                updated_at=NOW - timedelta(seconds=1),
            )
        )
    tools = ActionTools(
        factory,
        clock=lambda: NOW,
        id_generator=ids,
        reliability_policy=ReliabilityPolicy(initial_backoff_seconds=0),
        sleeper=lambda _: None,
    )

    result = tools.create_ticket(request, agent)

    assert result.operation_id == "OP-EXPIRED"
    assert result.idempotent_replay is True
    assert ReliabilityEventType.LEASE_RECOVERED in {
        event.event_type for event in tools.list_reliability_events(result.operation_id)
    }


def test_concurrent_duplicate_request_executes_only_once(
    tmp_path: Path,
    ids: Callable[[str], str],
) -> None:
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'concurrency.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory.begin() as session:
        seed_all(session)
    execution_started = Event()
    allow_completion = Event()

    class BlockingTicketTools(ActionTools):
        execution_calls = 0

        def _execute_ticket(
            self, session: Session, ticket_id: str, request: CreateTicketRequest
        ) -> None:
            self.execution_calls += 1
            execution_started.set()
            if not allow_completion.wait(timeout=5):
                raise RuntimeError("test did not release the action")
            super()._execute_ticket(session, ticket_id, request)

    tools = BlockingTicketTools(
        factory,
        clock=lambda: NOW,
        id_generator=ids,
        reliability_policy=ReliabilityPolicy(initial_backoff_seconds=0),
        sleeper=lambda _: None,
    )
    request = CreateTicketRequest(
        idempotency_key="concurrent-duplicate-key",
        case_id="CASE-1001",
        subject="Concurrent duplicate request",
        description="Only one caller may execute this action.",
    )
    agent = actor(ActorRole.AGENT)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(tools.create_ticket, request, agent)
            assert execution_started.wait(timeout=5)
            second = executor.submit(tools.create_ticket, request, agent)
            with pytest.raises(OperationInProgressError):
                second.result(timeout=5)
            allow_completion.set()
            result = first.result(timeout=5)
        assert result.verified is True
        assert tools.execution_calls == 1
        with factory() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(TicketRecord)
                    .where(TicketRecord.subject == request.subject)
                )
                == 1
            )
    finally:
        allow_completion.set()
        engine.dispose()
