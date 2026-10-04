import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from resolveops.database.event_records import (
    InboundEventRecord,
    ResourceEventCursorRecord,
)
from resolveops.database.records import CaseIssueRecord, RefundRecord
from resolveops.database.workflow_records import WorkflowEventRecord, WorkflowRunRecord
from resolveops.events.errors import EventConflictError
from resolveops.events.models import (
    EventReceipt,
    InboundEventStatus,
    RefundStatusChangedEvent,
)
from resolveops.models.refund import RefundKind, RefundStatus
from resolveops.workflows.case_state import (
    REFUND_OUTCOMES,
    refund_state_projection,
    synchronize_refund_state,
)
from resolveops.workflows.models import (
    WorkflowEventType,
    WorkflowLifecycleStatus,
    WorkflowOutcome,
)

ALLOWED_REFUND_TRANSITIONS: dict[RefundStatus, frozenset[RefundStatus]] = {
    RefundStatus.PENDING: frozenset(
        {
            RefundStatus.PROCESSING,
            RefundStatus.COMPLETED,
            RefundStatus.FAILED,
            RefundStatus.CANCELLED,
        }
    ),
    RefundStatus.PROCESSING: frozenset(
        {
            RefundStatus.COMPLETED,
            RefundStatus.FAILED,
            RefundStatus.CANCELLED,
        }
    ),
    RefundStatus.COMPLETED: frozenset(),
    RefundStatus.FAILED: frozenset(),
    RefundStatus.CANCELLED: frozenset(),
}


class RefundEventProcessor:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock or (lambda: datetime.now(UTC))

    def process(self, event: RefundStatusChangedEvent) -> EventReceipt:
        fingerprint = self._payload_hash(event)
        try:
            with self.session_factory.begin() as session:
                existing = session.get(InboundEventRecord, event.event_id)
                if existing is not None:
                    return self._replay_receipt(existing, fingerprint)
                now = self.clock()
                record = InboundEventRecord(
                    event_id=event.event_id,
                    event_type=event.event_type,
                    source=event.source,
                    payload_sha256=fingerprint,
                    payload=event.model_dump(mode="json"),
                    occurred_at=event.occurred_at,
                    status=InboundEventStatus.PROCESSED,
                    resource_type="refund",
                    resource_id=event.data.refund_id,
                    provider_reference=event.data.provider_reference,
                    error_code=None,
                    error_message=None,
                    received_at=now,
                    processed_at=now,
                )
                session.add(record)
                session.flush()
                message = self._apply_refund_event(session, record, event)
                return self._receipt(record, message=message)
        except IntegrityError:
            with self.session_factory() as session:
                existing = session.get(InboundEventRecord, event.event_id)
                if existing is None:
                    raise
                return self._replay_receipt(existing, fingerprint)

    def _apply_refund_event(
        self,
        session: Session,
        record: InboundEventRecord,
        event: RefundStatusChangedEvent,
    ) -> str:
        refund = session.scalar(
            select(RefundRecord)
            .where(RefundRecord.refund_id == event.data.refund_id)
            .with_for_update()
        )
        if refund is None:
            return self._reject(
                record,
                "refund_not_found",
                f"refund {event.data.refund_id} does not exist",
            )
        cursor = session.scalar(
            select(ResourceEventCursorRecord)
            .where(
                ResourceEventCursorRecord.resource_type == "refund",
                ResourceEventCursorRecord.resource_id == refund.refund_id,
            )
            .with_for_update()
        )
        if cursor is not None and event.data.provider_reference != cursor.provider_reference:
            return self._reject(
                record,
                "provider_reference_conflict",
                "provider reference does not match the previously authenticated refund record",
            )
        if event.occurred_at < refund.created_at:
            return self._reject(
                record,
                "invalid_refund_event_time",
                "refund status event cannot be earlier than refund creation",
            )
        if event.data.completed_at is not None and event.data.completed_at > event.occurred_at:
            return self._reject(
                record,
                "invalid_refund_completion_time",
                "refund completion cannot be later than its status event",
            )
        if cursor is not None and event.occurred_at < cursor.last_occurred_at:
            record.status = InboundEventStatus.IGNORED_STALE
            return "The authenticated event was stored but ignored because it was stale."

        target = RefundStatus(event.data.status)
        if target == refund.status:
            if target == RefundStatus.COMPLETED and refund.completed_at != event.data.completed_at:
                return self._reject(
                    record,
                    "terminal_event_conflict",
                    "completed refund event conflicts with the stored completion time",
                )
        elif target not in ALLOWED_REFUND_TRANSITIONS[refund.status]:
            return self._reject(
                record,
                "invalid_refund_transition",
                f"refund cannot move from {refund.status.value} to {target.value}",
            )
        elif (
            target == RefundStatus.COMPLETED
            and event.data.completed_at is not None
            and event.data.completed_at < refund.created_at
        ):
            return self._reject(
                record,
                "invalid_refund_completion_time",
                "refund completion cannot be earlier than refund creation",
            )
        else:
            refund.status = target
            refund.completed_at = event.data.completed_at

        if cursor is None:
            cursor = ResourceEventCursorRecord(
                resource_type="refund",
                resource_id=refund.refund_id,
                last_event_id=event.event_id,
                last_occurred_at=event.occurred_at,
                provider_reference=event.data.provider_reference,
                updated_at=self.clock(),
            )
            session.add(cursor)
        else:
            cursor.last_event_id = event.event_id
            cursor.last_occurred_at = event.occurred_at
            cursor.provider_reference = event.data.provider_reference
            cursor.updated_at = self.clock()
        session.flush()
        self._synchronize_settlement(session, refund, event)
        return f"Refund {refund.refund_id} status is {refund.status.value}."

    def _synchronize_settlement(
        self, session: Session, refund: RefundRecord, event: RefundStatusChangedEvent
    ) -> None:
        """Store the case projection and workflow observation with the provider event."""
        now = self.clock()
        synchronize_refund_state(session, refund, now)
        # A monitored return can be settled by more than one refund portion. Update
        # linked runs when any portion changes, not only the initially observed ID.
        related = select(RefundRecord).where(
            RefundRecord.order_id == refund.order_id,
            RefundRecord.kind == refund.kind,
            RefundRecord.currency == refund.currency,
        )
        if refund.kind == RefundKind.RETURN:
            related = related.where(RefundRecord.return_id == refund.return_id)
        else:
            related = related.where(RefundRecord.payment_id == refund.payment_id)
        related_refunds = {item.refund_id: item for item in session.scalars(related)}
        runs = list(
            session.scalars(
                select(WorkflowRunRecord)
                .join(CaseIssueRecord, WorkflowRunRecord.issue_id == CaseIssueRecord.issue_id)
                .where(
                    WorkflowRunRecord.outcome.in_(REFUND_OUTCOMES),
                    CaseIssueRecord.order_id == refund.order_id,
                )
                .with_for_update(of=WorkflowRunRecord)
            )
        )
        for run in runs:
            events = list(
                session.scalars(
                    select(WorkflowEventRecord).where(
                        WorkflowEventRecord.workflow_id == run.workflow_id
                    )
                )
            )
            linked_id = next(
                (
                    str(item.details[key])
                    for item in events
                    for key in ("verified_resource_id", "resource_id", "refund_id")
                    if item.details.get(key) in related_refunds
                ),
                None,
            )
            if linked_id is None:
                continue
            monitored_refund = related_refunds[linked_id]
            projection = refund_state_projection(session, monitored_refund)
            synchronize_refund_state(session, monitored_refund, now, issue_id=run.issue_id)
            run.outcome = projection.outcome
            if projection.outcome == WorkflowOutcome.WAITING_EXTERNAL:
                run.status = WorkflowLifecycleStatus.WAITING_EXTERNAL
                run.completed_at = None
                # Preserve whether this run submitted or only monitored the refund.
                if any(item.event_type == WorkflowEventType.ACTION_EXECUTED for item in events):
                    run.outcome = WorkflowOutcome.REFUND_SUBMITTED
            elif projection.outcome == WorkflowOutcome.REFUND_SETTLED:
                run.status = WorkflowLifecycleStatus.COMPLETED
                run.completed_at = now
            else:
                run.status = WorkflowLifecycleStatus.ESCALATED
                run.completed_at = now
            run.error_code = projection.error_code
            run.error_message = projection.summary if projection.error_code else None
            run.updated_at = now
            last_sequence = session.scalar(
                select(func.max(WorkflowEventRecord.sequence_number)).where(
                    WorkflowEventRecord.workflow_id == run.workflow_id
                )
            )
            event_key = f"{run.workflow_id}:{event.event_id}".encode()
            session.add(
                WorkflowEventRecord(
                    event_id=f"WFE-SETTLEMENT-{hashlib.sha256(event_key).hexdigest()[:32]}",
                    workflow_id=run.workflow_id,
                    sequence_number=(last_sequence or 0) + 1,
                    event_type=WorkflowEventType.REFUND_STATUS_CHANGED,
                    actor_id=None,
                    actor_role=None,
                    details={
                        "refund_id": refund.refund_id,
                        "verified_resource_id": monitored_refund.refund_id,
                        "provider_status": refund.status.value,
                        "inbound_event_id": event.event_id,
                        "source": event.source,
                        "outcome": projection.outcome.value,
                        "completed_at": refund.completed_at.isoformat()
                        if refund.completed_at
                        else None,
                    },
                    occurred_at=now,
                )
            )

    @staticmethod
    def _reject(record: InboundEventRecord, code: str, message: str) -> str:
        record.status = InboundEventStatus.REJECTED
        record.error_code = code
        record.error_message = message
        return f"Event was rejected: {message}"

    def _replay_receipt(self, record: InboundEventRecord, fingerprint: str) -> EventReceipt:
        if record.payload_sha256 != fingerprint:
            raise EventConflictError(
                "event_id_conflict",
                f"event ID {record.event_id} was already used for a different payload",
            )
        return self._receipt(
            record,
            message="The event was already received; no state was changed.",
            idempotent_replay=True,
        )

    @staticmethod
    def _receipt(
        record: InboundEventRecord,
        *,
        message: str,
        idempotent_replay: bool = False,
    ) -> EventReceipt:
        return EventReceipt(
            event_id=record.event_id,
            status=record.status,
            resource_id=record.resource_id,
            idempotent_replay=idempotent_replay,
            message=message,
            processed_at=record.processed_at,
        )

    @staticmethod
    def _payload_hash(event: RefundStatusChangedEvent) -> str:
        canonical = json.dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
