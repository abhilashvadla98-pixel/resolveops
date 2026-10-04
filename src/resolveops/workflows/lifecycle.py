import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from resolveops.database.workflow_records import (
    WorkflowApprovalRecord,
    WorkflowEventRecord,
    WorkflowRunRecord,
)
from resolveops.operations.auth import require_permission, require_refund_limit
from resolveops.operations.errors import OperationError
from resolveops.operations.models import ActorRole, IssueRefundRequest, OperationType, Permission
from resolveops.workflows.models import (
    ApprovalDecisionType,
    ApprovalStatus,
    WorkflowApproval,
    WorkflowApprovalDecision,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowLifecycleStatus,
    WorkflowOutcome,
    WorkflowRequest,
    WorkflowResult,
    WorkflowRun,
)


class WorkflowLifecycleError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class WorkflowConflictError(WorkflowLifecycleError):
    pass


class ApprovalDecisionError(WorkflowLifecycleError):
    pass


class WorkflowLifecycleStore:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] | None = None,
        id_generator: Callable[[str], str] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock or (lambda: datetime.now(UTC))
        self.id_generator = id_generator or (lambda prefix: f"{prefix}-{uuid4().hex.upper()}")

    def start(self, request: WorkflowRequest) -> tuple[WorkflowRun, bool]:
        fingerprint = self.request_fingerprint(request)
        now = self.clock()
        try:
            with self.session_factory.begin() as session:
                existing = session.get(WorkflowRunRecord, request.workflow_id)
                if existing is not None:
                    return self._matching_run(existing, request, fingerprint), False
                record = WorkflowRunRecord(
                    workflow_id=request.workflow_id,
                    thread_id=request.workflow_id,
                    case_id=request.case_id,
                    issue_id=request.issue_id,
                    request_fingerprint=fingerprint,
                    status=WorkflowLifecycleStatus.RUNNING,
                    outcome=None,
                    requested_by=request.actor.actor_id,
                    requested_role=request.actor.role,
                    error_code=None,
                    error_message=None,
                    created_at=now,
                    updated_at=now,
                    completed_at=None,
                )
                session.add(record)
                session.flush()
                self._add_event(
                    session,
                    record,
                    WorkflowEventType.STARTED,
                    actor_id=request.actor.actor_id,
                    actor_role=request.actor.role,
                )
                return self._run_from_record(record), True
        except IntegrityError:
            with self.session_factory() as session:
                existing = session.get(WorkflowRunRecord, request.workflow_id)
                if existing is None:
                    raise
                return self._matching_run(existing, request, fingerprint), False

    def get_run(self, workflow_id: str) -> WorkflowRun:
        with self.session_factory() as session:
            return self._run_from_record(self._required_run(session, workflow_id))

    def list_runs(self, *, case_id: str | None = None) -> list[WorkflowRun]:
        with self.session_factory() as session:
            statement = select(WorkflowRunRecord)
            if case_id is not None:
                statement = statement.where(WorkflowRunRecord.case_id == case_id)
            records = session.scalars(
                statement.order_by(
                    WorkflowRunRecord.created_at.desc(), WorkflowRunRecord.workflow_id
                )
            )
            return [self._run_from_record(record) for record in records]

    def request_refund_approval(
        self,
        *,
        workflow_id: str,
        request: IssueRefundRequest,
        requested_by: str,
        requested_role: ActorRole,
        reason: str,
    ) -> WorkflowApproval:
        approval_id = self._approval_id(workflow_id, OperationType.ISSUE_REFUND)
        with self.session_factory.begin() as session:
            existing = session.get(WorkflowApprovalRecord, approval_id)
            if existing is not None:
                self._validate_approval_payload(existing, request)
                return self._approval_from_record(existing)

            run = self._required_run(session, workflow_id, for_update=True)
            if run.status not in {
                WorkflowLifecycleStatus.RUNNING,
                WorkflowLifecycleStatus.WAITING_APPROVAL,
            }:
                raise WorkflowConflictError(
                    "workflow_not_active",
                    f"workflow {workflow_id} is not active",
                )
            now = self.clock()
            approval = WorkflowApprovalRecord(
                approval_id=approval_id,
                workflow_id=workflow_id,
                operation_type=OperationType.ISSUE_REFUND,
                status=ApprovalStatus.PENDING,
                case_id=request.case_id,
                issue_id=request.issue_id,
                payment_id=request.payment_id,
                amount=request.amount,
                currency=request.currency,
                reason=reason,
                requested_by=requested_by,
                requested_role=requested_role,
                requested_at=now,
                decided_by=None,
                decided_role=None,
                decision_note=None,
                decided_at=None,
            )
            session.add(approval)
            run.status = WorkflowLifecycleStatus.WAITING_APPROVAL
            run.updated_at = now
            self._add_event(
                session,
                run,
                WorkflowEventType.APPROVAL_REQUESTED,
                actor_id=requested_by,
                actor_role=requested_role,
                details={
                    "approval_id": approval_id,
                    "operation_type": OperationType.ISSUE_REFUND.value,
                    "amount": str(request.amount),
                    "currency": request.currency,
                },
            )
            return self._approval_from_record(approval)

    def get_approval(self, approval_id: str) -> WorkflowApproval:
        with self.session_factory() as session:
            record = session.get(WorkflowApprovalRecord, approval_id)
            if record is None:
                raise ApprovalDecisionError(
                    "approval_not_found", f"approval {approval_id} does not exist"
                )
            return self._approval_from_record(record)

    def list_approvals(
        self, *, approval_status: ApprovalStatus | None = None
    ) -> list[WorkflowApproval]:
        with self.session_factory() as session:
            statement = select(WorkflowApprovalRecord)
            if approval_status is not None:
                statement = statement.where(WorkflowApprovalRecord.status == approval_status)
            records = session.scalars(
                statement.order_by(
                    WorkflowApprovalRecord.requested_at.desc(),
                    WorkflowApprovalRecord.approval_id,
                )
            )
            return [self._approval_from_record(record) for record in records]

    def decide_approval(self, decision: WorkflowApprovalDecision) -> WorkflowApproval:
        with self.session_factory.begin() as session:
            record = session.scalar(
                select(WorkflowApprovalRecord)
                .where(WorkflowApprovalRecord.approval_id == decision.approval_id)
                .with_for_update()
            )
            if record is None:
                raise ApprovalDecisionError(
                    "approval_not_found",
                    f"approval {decision.approval_id} does not exist",
                )
            desired_status = (
                ApprovalStatus.APPROVED
                if decision.decision == ApprovalDecisionType.APPROVE
                else ApprovalStatus.REJECTED
            )
            if record.status != ApprovalStatus.PENDING:
                if (
                    record.status == desired_status
                    and record.decided_by == decision.actor.actor_id
                    and record.decided_role == decision.actor.role
                    and record.decision_note == decision.note
                ):
                    return self._approval_from_record(record)
                raise ApprovalDecisionError(
                    "approval_already_decided",
                    f"approval {record.approval_id} is already {record.status.value}",
                )
            self._authorize_decider(record, decision)

            now = self.clock()
            record.status = desired_status
            record.decided_by = decision.actor.actor_id
            record.decided_role = decision.actor.role
            record.decision_note = decision.note
            record.decided_at = now
            run = self._required_run(session, record.workflow_id, for_update=True)
            run.status = WorkflowLifecycleStatus.RUNNING
            run.updated_at = now
            event_type = (
                WorkflowEventType.APPROVAL_APPROVED
                if desired_status == ApprovalStatus.APPROVED
                else WorkflowEventType.APPROVAL_REJECTED
            )
            self._add_event(
                session,
                run,
                event_type,
                actor_id=decision.actor.actor_id,
                actor_role=decision.actor.role,
                details={"approval_id": record.approval_id, "note": decision.note},
            )
            return self._approval_from_record(record)

    def finish(self, result: WorkflowResult) -> WorkflowRun:
        with self.session_factory.begin() as session:
            record = self._required_run(session, result.workflow_id, for_update=True)
            lifecycle_status = (
                WorkflowLifecycleStatus.ESCALATED
                if result.outcome == WorkflowOutcome.NEEDS_REVIEW
                else WorkflowLifecycleStatus.WAITING_EXTERNAL
                if result.outcome
                in {WorkflowOutcome.REFUND_SUBMITTED, WorkflowOutcome.WAITING_EXTERNAL}
                else WorkflowLifecycleStatus.COMPLETED
            )
            if record.status in {
                WorkflowLifecycleStatus.COMPLETED,
                WorkflowLifecycleStatus.ESCALATED,
            }:
                if record.status != lifecycle_status or record.outcome != result.outcome:
                    raise WorkflowConflictError(
                        "workflow_terminal_conflict",
                        "stored terminal workflow result does not match the graph result",
                    )
                return self._run_from_record(record)
            now = self.clock()
            if record.status == lifecycle_status and record.outcome == result.outcome:
                return self._run_from_record(record)
            record.status = lifecycle_status
            record.outcome = result.outcome
            record.error_code = result.error_code
            record.error_message = result.error_message
            record.updated_at = now
            record.completed_at = (
                None if lifecycle_status == WorkflowLifecycleStatus.WAITING_EXTERNAL else now
            )
            event_type = (
                WorkflowEventType.ESCALATED
                if lifecycle_status == WorkflowLifecycleStatus.ESCALATED
                else WorkflowEventType.REFUND_STATUS_CHANGED
                if lifecycle_status == WorkflowLifecycleStatus.WAITING_EXTERNAL
                else WorkflowEventType.COMPLETED
            )
            self._add_event(
                session,
                record,
                event_type,
                details={
                    "outcome": result.outcome.value,
                    "verified_resource_id": result.verified_resource_id,
                },
            )
            return self._run_from_record(record)

    def fail(self, workflow_id: str, *, code: str, message: str) -> WorkflowRun:
        with self.session_factory.begin() as session:
            record = self._required_run(session, workflow_id, for_update=True)
            now = self.clock()
            record.status = WorkflowLifecycleStatus.FAILED
            record.error_code = code
            record.error_message = message
            record.updated_at = now
            record.completed_at = now
            self._add_event(
                session,
                record,
                WorkflowEventType.FAILED,
                details={"error_code": code, "message": message},
            )
            return self._run_from_record(record)

    def list_events(self, workflow_id: str) -> list[WorkflowEvent]:
        with self.session_factory() as session:
            self._required_run(session, workflow_id)
            records = session.scalars(
                select(WorkflowEventRecord)
                .where(WorkflowEventRecord.workflow_id == workflow_id)
                .order_by(WorkflowEventRecord.sequence_number)
            )
            return [self._event_from_record(record) for record in records]

    def record_event_once(
        self,
        workflow_id: str,
        event_type: WorkflowEventType,
        *,
        actor_id: str | None = None,
        actor_role: ActorRole | None = None,
        details: dict[str, object] | None = None,
    ) -> WorkflowEvent:
        """Persist one replay-safe lifecycle event for a completed graph stage."""
        with self.session_factory.begin() as session:
            run = self._required_run(session, workflow_id, for_update=True)
            existing = session.scalar(
                select(WorkflowEventRecord).where(
                    WorkflowEventRecord.workflow_id == workflow_id,
                    WorkflowEventRecord.event_type == event_type,
                )
            )
            if existing is not None:
                return self._event_from_record(existing)
            self._add_event(
                session,
                run,
                event_type,
                actor_id=actor_id,
                actor_role=actor_role,
                details=details,
            )
            session.flush()
            created = session.scalar(
                select(WorkflowEventRecord).where(
                    WorkflowEventRecord.workflow_id == workflow_id,
                    WorkflowEventRecord.event_type == event_type,
                )
            )
            if created is None:
                raise RuntimeError("workflow event was not persisted")
            return self._event_from_record(created)

    @staticmethod
    def request_fingerprint(request: WorkflowRequest) -> str:
        canonical = json.dumps(
            request.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _matching_run(
        self, record: WorkflowRunRecord, request: WorkflowRequest, fingerprint: str
    ) -> WorkflowRun:
        if record.request_fingerprint != fingerprint:
            raise WorkflowConflictError(
                "workflow_request_conflict",
                f"workflow ID {request.workflow_id} was already used for a different request",
            )
        return self._run_from_record(record)

    @staticmethod
    def _authorize_decider(
        record: WorkflowApprovalRecord, decision: WorkflowApprovalDecision
    ) -> None:
        if decision.actor.actor_id == record.requested_by:
            raise ApprovalDecisionError(
                "approval_permission_denied",
                "A different authorized person must review the proposal.",
            )
        if decision.actor.role not in {ActorRole.APPROVER, ActorRole.SYSTEM}:
            raise ApprovalDecisionError(
                "approval_permission_denied",
                "only an approver or system actor may decide a refund approval",
            )
        try:
            require_permission(decision.actor, Permission.ISSUE_REFUND)
            require_refund_limit(decision.actor, record.amount, record.currency)
        except OperationError as exc:
            raise ApprovalDecisionError(exc.code, exc.message) from exc

    @staticmethod
    def _validate_approval_payload(
        record: WorkflowApprovalRecord, request: IssueRefundRequest
    ) -> None:
        if (
            record.case_id != request.case_id
            or record.issue_id != request.issue_id
            or record.payment_id != request.payment_id
            or record.amount != request.amount
            or record.currency != request.currency
        ):
            raise WorkflowConflictError(
                "approval_payload_conflict",
                "stored approval does not match the requested refund",
            )

    def _add_event(
        self,
        session: Session,
        workflow: WorkflowRunRecord,
        event_type: WorkflowEventType,
        *,
        actor_id: str | None = None,
        actor_role: ActorRole | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        last_sequence = session.scalar(
            select(func.max(WorkflowEventRecord.sequence_number)).where(
                WorkflowEventRecord.workflow_id == workflow.workflow_id
            )
        )
        session.add(
            WorkflowEventRecord(
                event_id=self.id_generator("WFE"),
                workflow_id=workflow.workflow_id,
                sequence_number=(last_sequence or 0) + 1,
                event_type=event_type,
                actor_id=actor_id,
                actor_role=actor_role,
                details=details or {},
                occurred_at=self.clock(),
            )
        )

    @staticmethod
    def _required_run(
        session: Session, workflow_id: str, *, for_update: bool = False
    ) -> WorkflowRunRecord:
        statement = select(WorkflowRunRecord).where(WorkflowRunRecord.workflow_id == workflow_id)
        if for_update:
            statement = statement.with_for_update()
        record = session.scalar(statement)
        if record is None:
            raise WorkflowLifecycleError(
                "workflow_not_found", f"workflow {workflow_id} does not exist"
            )
        return record

    @staticmethod
    def _approval_id(workflow_id: str, operation_type: OperationType) -> str:
        raw = f"{workflow_id}:{operation_type.value}".encode()
        return f"APR-{hashlib.sha256(raw).hexdigest()[:24].upper()}"

    @staticmethod
    def _run_from_record(record: WorkflowRunRecord) -> WorkflowRun:
        return WorkflowRun(
            workflow_id=record.workflow_id,
            thread_id=record.thread_id,
            case_id=record.case_id,
            issue_id=record.issue_id,
            status=record.status,
            outcome=record.outcome,
            requested_by=record.requested_by,
            requested_role=record.requested_role,
            created_at=record.created_at,
            updated_at=record.updated_at,
            completed_at=record.completed_at,
            error_code=record.error_code,
            error_message=record.error_message,
        )

    @staticmethod
    def _approval_from_record(record: WorkflowApprovalRecord) -> WorkflowApproval:
        return WorkflowApproval(
            approval_id=record.approval_id,
            workflow_id=record.workflow_id,
            case_id=record.case_id,
            issue_id=record.issue_id,
            status=record.status,
            payment_id=record.payment_id,
            amount=record.amount,
            currency=record.currency,
            reason=record.reason,
            requested_by=record.requested_by,
            requested_role=record.requested_role,
            requested_at=record.requested_at,
            decided_by=record.decided_by,
            decided_role=record.decided_role,
            decision_note=record.decision_note,
            decided_at=record.decided_at,
        )

    @staticmethod
    def _event_from_record(record: WorkflowEventRecord) -> WorkflowEvent:
        return WorkflowEvent(
            event_id=record.event_id,
            workflow_id=record.workflow_id,
            sequence_number=record.sequence_number,
            event_type=record.event_type,
            actor_id=record.actor_id,
            actor_role=record.actor_role,
            details=record.details,
            occurred_at=record.occurred_at,
        )
