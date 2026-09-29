import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Any
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from resolveops.database.action_records import (
    AuditEventRecord,
    OperationRecord,
    ReliabilityEventRecord,
)
from resolveops.employee_it.actions import execute_repository_access, verify_repository_access
from resolveops.employee_it.models import GrantRepositoryAccessRequest
from resolveops.observability.models import TraceComponent, TraceStatus
from resolveops.observability.sinks import DEFAULT_TRACE_SINK, TraceSink
from resolveops.observability.tracing import observed_span, record_trace_event
from resolveops.operations.auth import require_permission, require_refund_limit
from resolveops.operations.communications import (
    execute_notification,
    execute_ticket,
    verify_notification,
    verify_ticket,
)
from resolveops.operations.errors import (
    ApprovalRequiredError,
    AuthorizationError,
    IdempotencyConflictError,
    OperationError,
    OperationInProgressError,
    OperationTimeoutError,
    PreviousOperationFailedError,
    RecoveryRequiredError,
    ResourceNotFoundError,
    RetryExhaustedError,
    TransientOperationError,
    VerificationError,
)
from resolveops.operations.models import (
    Actor,
    AuditEventType,
    CompensationStrategy,
    CreateTicketRequest,
    IssueRefundRequest,
    OperationRecoveryPlan,
    OperationResult,
    OperationStatus,
    OperationType,
    Permission,
    RecoveryDisposition,
    ReliabilityEvent,
    ReliabilityEventType,
    SendNotificationRequest,
)
from resolveops.operations.refunds import execute_refund, verify_refund
from resolveops.operations.reliability import (
    DEFAULT_SLEEPER,
    ReliabilityPolicy,
    Sleeper,
)

ActionRequest = (
    IssueRefundRequest
    | SendNotificationRequest
    | CreateTicketRequest
    | GrantRepositoryAccessRequest
)


@dataclass(frozen=True)
class _StartedOperation:
    operation_id: str
    resource_id: str | None
    needs_execution: bool
    existing: bool
    recovery_verification: bool


class ActionTools:
    """Run controlled writes for an actor supplied by a trusted authentication boundary."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] | None = None,
        id_generator: Callable[[str], str] | None = None,
        reliability_policy: ReliabilityPolicy | None = None,
        sleeper: Sleeper = DEFAULT_SLEEPER,
        monotonic_clock: Callable[[], float] = monotonic,
        observability_sink: TraceSink | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock or (lambda: datetime.now(UTC))
        self.id_generator = id_generator or (lambda prefix: f"{prefix}-{uuid4().hex.upper()}")
        self.reliability_policy = reliability_policy or ReliabilityPolicy()
        self.sleeper = sleeper
        self.monotonic_clock = monotonic_clock
        self.observability_sink = observability_sink or DEFAULT_TRACE_SINK

    def issue_refund(self, request: IssueRefundRequest, actor: Actor) -> OperationResult:
        return self._perform(
            request=request,
            actor=actor,
            operation_type=OperationType.ISSUE_REFUND,
            permission=Permission.ISSUE_REFUND,
            case_id=request.case_id,
            issue_id=request.issue_id,
            resource_type="refund",
            authorize=lambda: require_refund_limit(actor, request.amount, request.currency),
            execute=self._execute_refund,
            verify=self._verify_refund,
        )

    def send_notification(self, request: SendNotificationRequest, actor: Actor) -> OperationResult:
        return self._perform(
            request=request,
            actor=actor,
            operation_type=OperationType.SEND_NOTIFICATION,
            permission=Permission.SEND_NOTIFICATION,
            case_id=request.case_id,
            issue_id=None,
            resource_type="notification",
            authorize=lambda: None,
            execute=self._execute_notification,
            verify=self._verify_notification,
        )

    def create_ticket(self, request: CreateTicketRequest, actor: Actor) -> OperationResult:
        return self._perform(
            request=request,
            actor=actor,
            operation_type=OperationType.CREATE_TICKET,
            permission=Permission.CREATE_TICKET,
            case_id=request.case_id,
            issue_id=None,
            resource_type="ticket",
            authorize=lambda: None,
            execute=self._execute_ticket,
            verify=self._verify_ticket,
        )

    def grant_repository_access(
        self, request: GrantRepositoryAccessRequest, actor: Actor
    ) -> OperationResult:
        return self._perform(
            request=request,
            actor=actor,
            operation_type=OperationType.GRANT_REPOSITORY_ACCESS,
            permission=Permission.GRANT_REPOSITORY_ACCESS,
            case_id=request.case_id,
            issue_id=request.access_request_id,
            resource_type="git_repository_access",
            authorize=lambda: None,
            execute=self._execute_repository_access,
            verify=self._verify_repository_access,
        )

    def recover_refund(self, request: IssueRefundRequest, actor: Actor) -> OperationResult:
        return self._perform(
            request=request,
            actor=actor,
            operation_type=OperationType.ISSUE_REFUND,
            permission=Permission.ISSUE_REFUND,
            case_id=request.case_id,
            issue_id=request.issue_id,
            resource_type="refund",
            authorize=lambda: require_refund_limit(actor, request.amount, request.currency),
            execute=self._execute_refund,
            verify=self._verify_refund,
            allow_verification_recovery=True,
        )

    def recover_notification(
        self, request: SendNotificationRequest, actor: Actor
    ) -> OperationResult:
        return self._perform(
            request=request,
            actor=actor,
            operation_type=OperationType.SEND_NOTIFICATION,
            permission=Permission.SEND_NOTIFICATION,
            case_id=request.case_id,
            issue_id=None,
            resource_type="notification",
            authorize=lambda: None,
            execute=self._execute_notification,
            verify=self._verify_notification,
            allow_verification_recovery=True,
        )

    def recover_ticket(self, request: CreateTicketRequest, actor: Actor) -> OperationResult:
        return self._perform(
            request=request,
            actor=actor,
            operation_type=OperationType.CREATE_TICKET,
            permission=Permission.CREATE_TICKET,
            case_id=request.case_id,
            issue_id=None,
            resource_type="ticket",
            authorize=lambda: None,
            execute=self._execute_ticket,
            verify=self._verify_ticket,
            allow_verification_recovery=True,
        )

    def recover_repository_access(
        self, request: GrantRepositoryAccessRequest, actor: Actor
    ) -> OperationResult:
        return self._perform(
            request=request,
            actor=actor,
            operation_type=OperationType.GRANT_REPOSITORY_ACCESS,
            permission=Permission.GRANT_REPOSITORY_ACCESS,
            case_id=request.case_id,
            issue_id=request.access_request_id,
            resource_type="git_repository_access",
            authorize=lambda: None,
            execute=self._execute_repository_access,
            verify=self._verify_repository_access,
            allow_verification_recovery=True,
        )

    def get_recovery_plan(self, idempotency_key: str) -> OperationRecoveryPlan:
        with self.session_factory() as session:
            operation = session.scalar(
                select(OperationRecord).where(OperationRecord.idempotency_key == idempotency_key)
            )
            if operation is None:
                raise ResourceNotFoundError(
                    "operation_not_found",
                    f"operation for idempotency key {idempotency_key} does not exist",
                )
            return self._recovery_plan(operation)

    def list_reliability_events(self, operation_id: str) -> list[ReliabilityEvent]:
        with self.session_factory() as session:
            self._required_operation(session, operation_id)
            records = session.scalars(
                select(ReliabilityEventRecord)
                .where(ReliabilityEventRecord.operation_id == operation_id)
                .order_by(ReliabilityEventRecord.sequence_number)
            )
            return [self._reliability_event_from_record(record) for record in records]

    def _perform[RequestT: ActionRequest](
        self,
        *,
        request: RequestT,
        actor: Actor,
        operation_type: OperationType,
        permission: Permission,
        case_id: str,
        issue_id: str | None,
        resource_type: str,
        authorize: Callable[[], None],
        execute: Callable[[Session, str, RequestT], None],
        verify: Callable[[Session, str, RequestT], bool],
        allow_verification_recovery: bool = False,
    ) -> OperationResult:
        with observed_span(
            TraceComponent.TOOL,
            operation_type.value,
            sink=self.observability_sink,
            attributes={
                "actor_role": actor.role.value,
                "recovery": allow_verification_recovery,
            },
        ) as span:
            result = self._perform_unobserved(
                request=request,
                actor=actor,
                operation_type=operation_type,
                permission=permission,
                case_id=case_id,
                issue_id=issue_id,
                resource_type=resource_type,
                authorize=authorize,
                execute=execute,
                verify=verify,
                allow_verification_recovery=allow_verification_recovery,
            )
            span.set_attribute("verified", result.verified)
            span.set_attribute("idempotent_replay", result.idempotent_replay)
            span.set_attribute("operation_status", result.status.value)
            return result

    def _perform_unobserved[RequestT: ActionRequest](
        self,
        *,
        request: RequestT,
        actor: Actor,
        operation_type: OperationType,
        permission: Permission,
        case_id: str,
        issue_id: str | None,
        resource_type: str,
        authorize: Callable[[], None],
        execute: Callable[[Session, str, RequestT], None],
        verify: Callable[[Session, str, RequestT], bool],
        allow_verification_recovery: bool = False,
    ) -> OperationResult:
        payload_hash = self._payload_hash(operation_type, request)
        started = self._start_operation(
            request=request,
            actor=actor,
            operation_type=operation_type,
            payload_hash=payload_hash,
            case_id=case_id,
            issue_id=issue_id,
            allow_verification_recovery=allow_verification_recovery,
        )
        if started.needs_execution:
            try:
                require_permission(actor, permission)
                authorize()
            except (AuthorizationError, ApprovalRequiredError) as exc:
                self._fail_operation(started.operation_id, actor, exc, AuditEventType.DENIED)
                raise

            self._authorize_operation(started.operation_id, actor)
            resource_id = self.id_generator(self._resource_prefix(operation_type))
            try:
                self._execute_with_retries(
                    operation_id=started.operation_id,
                    actor=actor,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    request=request,
                    execute=execute,
                )
            except OperationError as exc:
                if not isinstance(exc, RetryExhaustedError):
                    self._record_permanent_execution_failure(
                        started.operation_id,
                        actor,
                        exc,
                    )
                raise
            except Exception:
                internal_error = OperationError(
                    "action_execution_failed", "action execution failed unexpectedly"
                )
                self._record_permanent_execution_failure(
                    started.operation_id,
                    actor,
                    internal_error,
                )
                raise
        else:
            if started.resource_id is None:
                raise VerificationError(
                    "missing_operation_result", "executed operation has no resource ID"
                )
            resource_id = started.resource_id

        self._verify_with_retries(
            operation_id=started.operation_id,
            actor=actor,
            resource_type=resource_type,
            resource_id=resource_id,
            request=request,
            verify=verify,
            recovery=started.recovery_verification,
        )
        return OperationResult(
            operation_id=started.operation_id,
            operation_type=operation_type,
            resource_id=resource_id,
            status=OperationStatus.COMPLETED,
            verified=True,
            idempotent_replay=started.existing,
        )

    def _start_operation(
        self,
        *,
        request: ActionRequest,
        actor: Actor,
        operation_type: OperationType,
        payload_hash: str,
        case_id: str,
        issue_id: str | None,
        allow_verification_recovery: bool,
    ) -> _StartedOperation:
        with self.session_factory.begin() as session:
            existing = session.scalar(
                select(OperationRecord)
                .where(OperationRecord.idempotency_key == request.idempotency_key)
                .with_for_update()
            )
            if existing is not None:
                return self._existing_operation(
                    session,
                    existing,
                    actor,
                    operation_type,
                    payload_hash,
                    allow_verification_recovery=allow_verification_recovery,
                )

        operation_id = self.id_generator("OP")
        now = self.clock()
        try:
            with self.session_factory.begin() as session:
                operation = OperationRecord(
                    operation_id=operation_id,
                    idempotency_key=request.idempotency_key,
                    operation_type=operation_type,
                    payload_hash=payload_hash,
                    status=OperationStatus.STARTED,
                    actor_id=actor.actor_id,
                    actor_role=actor.role,
                    case_id=case_id,
                    issue_id=issue_id,
                    attempt_count=0,
                    verification_attempt_count=0,
                    max_attempts=self.reliability_policy.max_attempts,
                    last_error_retryable=False,
                    last_attempt_at=None,
                    next_attempt_at=None,
                    lease_expires_at=now + timedelta(seconds=self.reliability_policy.lease_seconds),
                    created_at=now,
                    updated_at=now,
                )
                session.add(operation)
                self._add_audit(session, operation, actor, AuditEventType.REQUESTED)
        except IntegrityError:
            with self.session_factory.begin() as session:
                existing = session.scalar(
                    select(OperationRecord)
                    .where(OperationRecord.idempotency_key == request.idempotency_key)
                    .with_for_update()
                )
                if existing is None:
                    raise
                return self._existing_operation(
                    session,
                    existing,
                    actor,
                    operation_type,
                    payload_hash,
                    allow_verification_recovery=allow_verification_recovery,
                )
        return _StartedOperation(operation_id, None, True, False, False)

    def _existing_operation(
        self,
        session: Session,
        operation: OperationRecord,
        actor: Actor,
        operation_type: OperationType,
        payload_hash: str,
        *,
        allow_verification_recovery: bool,
    ) -> _StartedOperation:
        if (
            operation.operation_type != operation_type
            or operation.payload_hash != payload_hash
            or operation.actor_id != actor.actor_id
            or operation.actor_role != actor.role
        ):
            raise IdempotencyConflictError(
                "idempotency_conflict",
                "idempotency key was already used for a different action, payload, or actor",
            )
        if operation.status == OperationStatus.COMPLETED:
            if operation.result_resource_id is None:
                raise VerificationError(
                    "missing_operation_result", "completed operation has no resource ID"
                )
            return _StartedOperation(
                operation.operation_id,
                operation.result_resource_id,
                False,
                True,
                True,
            )
        if operation.status == OperationStatus.EXECUTED:
            return _StartedOperation(
                operation.operation_id,
                operation.result_resource_id,
                False,
                True,
                True,
            )
        if operation.status == OperationStatus.VERIFICATION_FAILED:
            if not allow_verification_recovery:
                raise RecoveryRequiredError(
                    "verification_recovery_required",
                    "the committed action needs an explicit verify-only recovery",
                )
            return _StartedOperation(
                operation.operation_id,
                operation.result_resource_id,
                False,
                True,
                True,
            )
        if operation.status == OperationStatus.STARTED:
            now = self.clock()
            blocked_until = operation.next_attempt_at or operation.lease_expires_at
            if blocked_until is not None and blocked_until > now:
                raise OperationInProgressError(
                    "operation_in_progress",
                    "an operation with this key is already in progress",
                )
            if operation.attempt_count >= operation.max_attempts:
                raise RecoveryRequiredError(
                    "recovery_attempts_exhausted",
                    "the operation exhausted its attempts and requires manual review",
                )
            operation.lease_expires_at = now + timedelta(
                seconds=self.reliability_policy.lease_seconds
            )
            operation.next_attempt_at = None
            operation.updated_at = now
            self._add_reliability_event(
                session,
                operation,
                ReliabilityEventType.LEASE_RECOVERED,
                attempt_number=operation.attempt_count + 1,
                details={"reason": "expired execution lease"},
            )
            return _StartedOperation(operation.operation_id, None, True, True, False)
        raise PreviousOperationFailedError(
            "previous_operation_failed",
            "the previous operation with this key failed; use a new key after correction",
        )

    def _execute_with_retries[RequestT: ActionRequest](
        self,
        *,
        operation_id: str,
        actor: Actor,
        resource_type: str,
        resource_id: str,
        request: RequestT,
        execute: Callable[[Session, str, RequestT], None],
    ) -> None:
        while True:
            attempt_number, max_attempts = self._prepare_execution_attempt(operation_id)
            started_at = self.monotonic_clock()
            try:
                with self.session_factory.begin() as session:
                    operation = self._required_operation(session, operation_id, for_update=True)
                    execute(session, resource_id, request)
                    elapsed = self.monotonic_clock() - started_at
                    if elapsed > self.reliability_policy.attempt_timeout_seconds:
                        raise OperationTimeoutError(
                            "operation_attempt_timed_out",
                            "the action attempt exceeded its transaction deadline",
                        )
                    operation.status = OperationStatus.EXECUTED
                    operation.result_resource_id = resource_id
                    operation.error_code = None
                    operation.error_message = None
                    operation.last_error_retryable = False
                    operation.next_attempt_at = None
                    operation.lease_expires_at = None
                    operation.updated_at = self.clock()
                    self._add_audit(
                        session,
                        operation,
                        actor,
                        AuditEventType.EXECUTED,
                        resource_type=resource_type,
                        resource_id=resource_id,
                    )
                    self._add_reliability_event(
                        session,
                        operation,
                        ReliabilityEventType.ATTEMPT_SUCCEEDED,
                        attempt_number=attempt_number,
                        details={"resource_type": resource_type},
                    )
                return
            except TransientOperationError as exc:
                delay = self._schedule_retry(
                    operation_id,
                    actor,
                    exc,
                    attempt_number=attempt_number,
                    max_attempts=max_attempts,
                )
                if delay is None:
                    raise RetryExhaustedError(
                        "retry_attempts_exhausted",
                        f"action failed after {attempt_number} safe attempts",
                    ) from exc
                self.sleeper(delay)

    def _prepare_execution_attempt(self, operation_id: str) -> tuple[int, int]:
        with self.session_factory.begin() as session:
            operation = self._required_operation(session, operation_id, for_update=True)
            if operation.attempt_count >= operation.max_attempts:
                raise RetryExhaustedError(
                    "retry_attempts_exhausted",
                    f"action already used all {operation.max_attempts} attempts",
                )
            now = self.clock()
            operation.attempt_count += 1
            operation.last_attempt_at = now
            operation.next_attempt_at = None
            operation.lease_expires_at = now + timedelta(
                seconds=self.reliability_policy.lease_seconds
            )
            operation.updated_at = now
            self._add_reliability_event(
                session,
                operation,
                ReliabilityEventType.ATTEMPT_STARTED,
                attempt_number=operation.attempt_count,
                details={
                    "timeout_seconds": self.reliability_policy.attempt_timeout_seconds,
                },
            )
            return operation.attempt_count, operation.max_attempts

    def _schedule_retry(
        self,
        operation_id: str,
        actor: Actor,
        error: TransientOperationError,
        *,
        attempt_number: int,
        max_attempts: int,
    ) -> float | None:
        delay = self.reliability_policy.backoff_seconds(attempt_number)
        with self.session_factory.begin() as session:
            operation = self._required_operation(session, operation_id, for_update=True)
            now = self.clock()
            operation.error_code = error.code
            operation.error_message = error.message
            operation.last_error_retryable = True
            operation.lease_expires_at = None
            operation.updated_at = now
            if attempt_number >= max_attempts:
                operation.status = OperationStatus.FAILED
                operation.error_code = "retry_attempts_exhausted"
                operation.error_message = (
                    f"action failed after {attempt_number} safe attempts: {error.message}"
                )
                operation.next_attempt_at = None
                self._add_audit(
                    session,
                    operation,
                    actor,
                    AuditEventType.FAILED,
                    details={
                        "error_code": operation.error_code,
                        "message": operation.error_message,
                    },
                )
                self._add_reliability_event(
                    session,
                    operation,
                    ReliabilityEventType.MANUAL_REVIEW_REQUIRED,
                    attempt_number=attempt_number,
                    details={
                        "last_error_code": error.code,
                        "compensation": CompensationStrategy.TRANSACTION_ROLLBACK.value,
                    },
                )
                return None

            operation.next_attempt_at = now + timedelta(seconds=delay)
            self._add_reliability_event(
                session,
                operation,
                ReliabilityEventType.RETRY_SCHEDULED,
                attempt_number=attempt_number,
                details={
                    "error_code": error.code,
                    "delay_seconds": delay,
                    "compensation": CompensationStrategy.TRANSACTION_ROLLBACK.value,
                },
            )
        record_trace_event(
            TraceComponent.TOOL,
            "execution_retry_scheduled",
            sink=self.observability_sink,
            status=TraceStatus.ERROR,
            attributes={
                "attempt_number": attempt_number,
                "delay_seconds": delay,
                "error_code": error.code,
            },
        )
        return delay

    def _record_permanent_execution_failure(
        self, operation_id: str, actor: Actor, error: OperationError
    ) -> None:
        self._fail_operation(operation_id, actor, error, AuditEventType.FAILED)
        with self.session_factory.begin() as session:
            operation = self._required_operation(session, operation_id, for_update=True)
            self._add_reliability_event(
                session,
                operation,
                ReliabilityEventType.MANUAL_REVIEW_REQUIRED,
                attempt_number=operation.attempt_count or None,
                details={
                    "error_code": error.code,
                    "compensation": CompensationStrategy.TRANSACTION_ROLLBACK.value,
                },
            )

    def _verify_with_retries[RequestT: ActionRequest](
        self,
        *,
        operation_id: str,
        actor: Actor,
        resource_type: str,
        resource_id: str,
        request: RequestT,
        verify: Callable[[Session, str, RequestT], bool],
        recovery: bool,
    ) -> None:
        for local_attempt in range(1, self.reliability_policy.max_attempts + 1):
            self._record_verification_attempt(operation_id)
            with self.session_factory() as verification_session:
                verified = verify(verification_session, resource_id, request)
            if verified:
                self._complete_operation(
                    operation_id,
                    actor,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    recovery=recovery,
                )
                return
            if local_attempt < self.reliability_policy.max_attempts:
                delay = self.reliability_policy.backoff_seconds(local_attempt)
                self._record_verification_retry(
                    operation_id,
                    local_attempt=local_attempt,
                    delay=delay,
                )
                self.sleeper(delay)

        error = VerificationError(
            "state_verification_failed",
            f"fresh database verification failed for {resource_type} {resource_id}",
        )
        self._verification_failed(operation_id, actor, resource_type, resource_id)
        raise error

    def _record_verification_attempt(self, operation_id: str) -> None:
        with self.session_factory.begin() as session:
            operation = self._required_operation(session, operation_id, for_update=True)
            operation.verification_attempt_count += 1
            operation.updated_at = self.clock()
            self._add_reliability_event(
                session,
                operation,
                ReliabilityEventType.VERIFICATION_ATTEMPTED,
                attempt_number=operation.verification_attempt_count,
            )

    def _record_verification_retry(
        self, operation_id: str, *, local_attempt: int, delay: float
    ) -> None:
        with self.session_factory.begin() as session:
            operation = self._required_operation(session, operation_id, for_update=True)
            self._add_reliability_event(
                session,
                operation,
                ReliabilityEventType.VERIFICATION_RETRY_SCHEDULED,
                attempt_number=operation.verification_attempt_count,
                details={
                    "local_attempt": local_attempt,
                    "delay_seconds": delay,
                },
            )
        record_trace_event(
            TraceComponent.TOOL,
            "verification_retry_scheduled",
            sink=self.observability_sink,
            status=TraceStatus.ERROR,
            attributes={
                "local_attempt": local_attempt,
                "delay_seconds": delay,
            },
        )

    def _authorize_operation(self, operation_id: str, actor: Actor) -> None:
        with self.session_factory.begin() as session:
            operation = self._required_operation(session, operation_id)
            operation.updated_at = self.clock()
            self._add_audit(session, operation, actor, AuditEventType.AUTHORIZED)

    def _fail_operation(
        self,
        operation_id: str,
        actor: Actor,
        error: OperationError,
        event_type: AuditEventType,
    ) -> None:
        with self.session_factory.begin() as session:
            operation = self._required_operation(session, operation_id)
            operation.status = OperationStatus.FAILED
            operation.error_code = error.code
            operation.error_message = error.message
            operation.last_error_retryable = False
            operation.next_attempt_at = None
            operation.lease_expires_at = None
            operation.updated_at = self.clock()
            self._add_audit(
                session,
                operation,
                actor,
                event_type,
                details={"error_code": error.code, "message": error.message},
            )

    def _verification_failed(
        self, operation_id: str, actor: Actor, resource_type: str, resource_id: str
    ) -> None:
        with self.session_factory.begin() as session:
            operation = self._required_operation(session, operation_id)
            operation.status = OperationStatus.VERIFICATION_FAILED
            operation.error_code = "state_verification_failed"
            operation.error_message = "fresh database verification failed"
            operation.last_error_retryable = False
            operation.next_attempt_at = None
            operation.lease_expires_at = None
            operation.updated_at = self.clock()
            self._add_audit(
                session,
                operation,
                actor,
                AuditEventType.VERIFICATION_FAILED,
                resource_type=resource_type,
                resource_id=resource_id,
            )
            self._add_reliability_event(
                session,
                operation,
                ReliabilityEventType.COMPENSATION_REQUIRED,
                attempt_number=operation.verification_attempt_count or None,
                details={
                    "reason": "committed action could not be independently verified",
                    "compensation": CompensationStrategy.MANUAL.value,
                    "automatic_compensation": False,
                },
            )

    def _complete_operation(
        self,
        operation_id: str,
        actor: Actor,
        *,
        resource_type: str,
        resource_id: str,
        recovery: bool,
    ) -> None:
        with self.session_factory.begin() as session:
            operation = self._required_operation(session, operation_id, for_update=True)
            previous_status = operation.status
            operation.status = OperationStatus.COMPLETED
            operation.error_code = None
            operation.error_message = None
            operation.last_error_retryable = False
            operation.next_attempt_at = None
            operation.lease_expires_at = None
            operation.updated_at = self.clock()
            if previous_status != OperationStatus.COMPLETED:
                self._add_audit(
                    session,
                    operation,
                    actor,
                    AuditEventType.VERIFIED,
                    resource_type=resource_type,
                    resource_id=resource_id,
                )
            if recovery:
                self._add_reliability_event(
                    session,
                    operation,
                    ReliabilityEventType.RECOVERY_VERIFIED,
                    attempt_number=operation.verification_attempt_count or None,
                    details={"previous_status": previous_status.value},
                )

    def _execute_refund(
        self, session: Session, refund_id: str, request: IssueRefundRequest
    ) -> None:
        execute_refund(session, refund_id, request, self.clock())

    def _execute_notification(
        self, session: Session, notification_id: str, request: SendNotificationRequest
    ) -> None:
        execute_notification(session, notification_id, request, self.clock())

    def _execute_ticket(
        self, session: Session, ticket_id: str, request: CreateTicketRequest
    ) -> None:
        execute_ticket(session, ticket_id, request, self.clock())

    @staticmethod
    def _verify_refund(session: Session, refund_id: str, request: IssueRefundRequest) -> bool:
        return verify_refund(session, refund_id, request)

    @staticmethod
    def _verify_notification(
        session: Session, notification_id: str, request: SendNotificationRequest
    ) -> bool:
        return verify_notification(session, notification_id, request)

    @staticmethod
    def _verify_ticket(session: Session, ticket_id: str, request: CreateTicketRequest) -> bool:
        return verify_ticket(session, ticket_id, request)

    def _execute_repository_access(
        self,
        session: Session,
        access_id: str,
        request: GrantRepositoryAccessRequest,
    ) -> None:
        execute_repository_access(session, access_id, request, self.clock())

    @staticmethod
    def _verify_repository_access(
        session: Session,
        access_id: str,
        request: GrantRepositoryAccessRequest,
    ) -> bool:
        return verify_repository_access(session, access_id, request)

    def _add_audit(
        self,
        session: Session,
        operation: OperationRecord,
        actor: Actor,
        event_type: AuditEventType,
        *,
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        last_sequence = session.scalar(
            select(func.max(AuditEventRecord.sequence_number)).where(
                AuditEventRecord.operation_id == operation.operation_id
            )
        )
        session.add(
            AuditEventRecord(
                audit_event_id=self.id_generator("AUD"),
                operation_id=operation.operation_id,
                sequence_number=(last_sequence or 0) + 1,
                event_type=event_type,
                actor_id=actor.actor_id,
                actor_role=actor.role,
                case_id=operation.case_id,
                issue_id=operation.issue_id,
                resource_type=resource_type,
                resource_id=resource_id,
                details=details or {},
                occurred_at=self.clock(),
            )
        )

    def _add_reliability_event(
        self,
        session: Session,
        operation: OperationRecord,
        event_type: ReliabilityEventType,
        *,
        attempt_number: int | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        last_sequence = session.scalar(
            select(func.max(ReliabilityEventRecord.sequence_number)).where(
                ReliabilityEventRecord.operation_id == operation.operation_id
            )
        )
        session.add(
            ReliabilityEventRecord(
                reliability_event_id=self.id_generator("REL"),
                operation_id=operation.operation_id,
                sequence_number=(last_sequence or 0) + 1,
                event_type=event_type,
                attempt_number=attempt_number,
                details=details or {},
                occurred_at=self.clock(),
            )
        )

    @staticmethod
    def _required_operation(
        session: Session, operation_id: str, *, for_update: bool = False
    ) -> OperationRecord:
        statement = select(OperationRecord).where(OperationRecord.operation_id == operation_id)
        if for_update:
            statement = statement.with_for_update()
        operation = session.scalar(statement)
        if operation is None:
            raise RuntimeError(f"operation {operation_id} disappeared")
        return operation

    def _recovery_plan(self, operation: OperationRecord) -> OperationRecoveryPlan:
        now = self.clock()
        if operation.status == OperationStatus.COMPLETED:
            disposition = RecoveryDisposition.COMPLETE
            compensation = CompensationStrategy.NONE
            safe_to_retry = False
            reason = "The action is complete; any replay will only verify the stored result."
        elif operation.status in {
            OperationStatus.EXECUTED,
            OperationStatus.VERIFICATION_FAILED,
        }:
            disposition = RecoveryDisposition.VERIFY_ONLY
            compensation = CompensationStrategy.MANUAL
            safe_to_retry = False
            reason = "The action may already be committed. Re-verify it and never execute it again."
        elif operation.status == OperationStatus.STARTED:
            blocked_until = operation.next_attempt_at or operation.lease_expires_at
            if blocked_until is not None and blocked_until > now:
                disposition = RecoveryDisposition.WAIT_FOR_LEASE
                safe_to_retry = False
                reason = "Another attempt owns the active lease or backoff window."
            elif operation.attempt_count < operation.max_attempts:
                disposition = RecoveryDisposition.RETRY_EXECUTION
                safe_to_retry = True
                reason = (
                    "No action commit was recorded and the execution lease expired; "
                    "retry with the same idempotency key."
                )
            else:
                disposition = RecoveryDisposition.MANUAL_REVIEW
                safe_to_retry = False
                reason = "All safe execution attempts were used."
            compensation = CompensationStrategy.TRANSACTION_ROLLBACK
        else:
            disposition = RecoveryDisposition.MANUAL_REVIEW
            safe_to_retry = False
            compensation = (
                CompensationStrategy.MANUAL
                if operation.result_resource_id is not None
                else CompensationStrategy.TRANSACTION_ROLLBACK
            )
            reason = "The failed operation requires a reviewed correction before a new key is used."
        return OperationRecoveryPlan(
            operation_id=operation.operation_id,
            idempotency_key=operation.idempotency_key,
            status=operation.status,
            disposition=disposition,
            compensation=compensation,
            safe_to_retry=safe_to_retry,
            attempt_count=operation.attempt_count,
            verification_attempt_count=operation.verification_attempt_count,
            max_attempts=operation.max_attempts,
            lease_expires_at=operation.lease_expires_at,
            next_attempt_at=operation.next_attempt_at,
            reason=reason,
        )

    @staticmethod
    def _reliability_event_from_record(
        record: ReliabilityEventRecord,
    ) -> ReliabilityEvent:
        return ReliabilityEvent(
            reliability_event_id=record.reliability_event_id,
            operation_id=record.operation_id,
            sequence_number=record.sequence_number,
            event_type=record.event_type,
            attempt_number=record.attempt_number,
            details=record.details,
            occurred_at=record.occurred_at,
        )

    @staticmethod
    def _payload_hash(operation_type: OperationType, request: BaseModel) -> str:
        payload: dict[str, Any] = request.model_dump(mode="json", exclude={"idempotency_key"})
        payload["operation_type"] = operation_type.value
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _resource_prefix(operation_type: OperationType) -> str:
        return {
            OperationType.ISSUE_REFUND: "REF",
            OperationType.SEND_NOTIFICATION: "NOTE",
            OperationType.CREATE_TICKET: "TKT",
            OperationType.GRANT_REPOSITORY_ACCESS: "GITACCESS",
        }[operation_type]
