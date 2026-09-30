from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from resolveops.agents.models import (
    AgentDomain,
    AgentInvocationRecord,
    AgentRunStatus,
    MultiAgentReasoningResult,
)
from resolveops.database.job_records import AgentJobEventRecord, AgentWorkflowJobRecord
from resolveops.jobs.models import (
    AgentJobEvent,
    AgentJobEventType,
    AgentJobStatus,
    AgentWorkflowJob,
    QueueHealth,
)


class QueueCapacityExceeded(RuntimeError):
    pass


class AgentJobStore:
    """PostgreSQL-backed durable queue; Redis is only an optional wake-up channel."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        capacity: int = 500,
        lease_seconds: int = 120,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if capacity < 1 or lease_seconds < 10:
            raise ValueError("queue capacity and lease must be positive")
        self.session_factory = session_factory
        self.capacity = capacity
        self.lease_seconds = lease_seconds
        self.clock = clock or (lambda: datetime.now(UTC))

    def enqueue(
        self,
        *,
        tenant_id: str,
        workflow_id: str,
        case_id: str,
        domain: AgentDomain,
        objective: str,
        idempotency_key: str,
        max_attempts: int = 2,
    ) -> AgentWorkflowJob:
        now = self.clock()
        with self.session_factory.begin() as session:
            existing = session.scalar(
                select(AgentWorkflowJobRecord).where(
                    AgentWorkflowJobRecord.tenant_id == tenant_id,
                    AgentWorkflowJobRecord.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return self._model(existing)
            active = session.scalar(
                select(func.count())
                .select_from(AgentWorkflowJobRecord)
                .where(
                    AgentWorkflowJobRecord.status.in_(
                        [AgentJobStatus.PENDING, AgentJobStatus.RUNNING, AgentJobStatus.RETRYING]
                    )
                )
            )
            if int(active or 0) >= self.capacity:
                raise QueueCapacityExceeded("agent queue is at capacity")
            record = AgentWorkflowJobRecord(
                job_id=f"AJOB-{uuid4().hex[:20]}",
                tenant_id=tenant_id,
                workflow_id=workflow_id,
                case_id=case_id,
                domain=domain,
                objective=objective,
                idempotency_key=idempotency_key,
                status=AgentJobStatus.PENDING,
                attempts=0,
                max_attempts=max_attempts,
                created_at=now,
                available_at=now,
                started_at=None,
                finished_at=None,
                lease_expires_at=None,
                worker_id=None,
                result=None,
                error_classification=None,
            )
            session.add(record)
            session.flush()
            self._event(session, record, AgentJobEventType.QUEUED)
            return self._model(record)

    def claim_next(self, worker_id: str) -> AgentWorkflowJob | None:
        now = self.clock()
        with self.session_factory.begin() as session:
            record = session.scalar(
                select(AgentWorkflowJobRecord)
                .where(
                    AgentWorkflowJobRecord.status.in_(
                        [AgentJobStatus.PENDING, AgentJobStatus.RETRYING]
                    ),
                    AgentWorkflowJobRecord.available_at <= now,
                    AgentWorkflowJobRecord.attempts < AgentWorkflowJobRecord.max_attempts,
                )
                .order_by(AgentWorkflowJobRecord.created_at, AgentWorkflowJobRecord.job_id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if record is None:
                return None
            record.status = AgentJobStatus.RUNNING
            record.attempts += 1
            record.started_at = record.started_at or now
            record.worker_id = worker_id
            record.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            self._event(session, record, AgentJobEventType.CLAIMED, {"worker_id": worker_id})
            return self._model(record)

    def complete(self, job_id: str, worker_id: str, result: MultiAgentReasoningResult) -> None:
        with self.session_factory.begin() as session:
            record = self._owned_running(session, job_id, worker_id)
            record.status = AgentJobStatus.COMPLETED
            record.finished_at = self.clock()
            record.lease_expires_at = None
            record.result = result.model_dump(mode="json")
            self._event(session, record, AgentJobEventType.COMPLETED)

    def record_agent_progress(
        self, job_id: str, worker_id: str, run: AgentInvocationRecord
    ) -> None:
        with self.session_factory.begin() as session:
            job = self._owned_running(session, job_id, worker_id)
            if job.tenant_id != run.tenant_id or job.workflow_id != run.workflow_id:
                raise ValueError("agent progress does not belong to the claimed job")
            if run.status == AgentRunStatus.RUNNING:
                event_type = AgentJobEventType.AGENT_STARTED
            elif run.status == AgentRunStatus.COMPLETED:
                event_type = AgentJobEventType.AGENT_COMPLETED
            else:
                event_type = AgentJobEventType.AGENT_FAILED
            details = {
                "role": run.role.value,
                "agent_run_id": run.agent_run_id,
            }
            if run.input_tokens is not None:
                details["input_tokens"] = str(run.input_tokens)
            if run.output_tokens is not None:
                details["output_tokens"] = str(run.output_tokens)
            if run.error_classification is not None:
                details["error_classification"] = run.error_classification
            self._event(session, job, event_type, details)

    def fail(self, job_id: str, worker_id: str, classification: str) -> AgentJobStatus:
        now = self.clock()
        with self.session_factory.begin() as session:
            record = self._owned_running(session, job_id, worker_id)
            record.error_classification = classification[:100]
            record.lease_expires_at = None
            if record.attempts < record.max_attempts:
                record.status = AgentJobStatus.RETRYING
                record.available_at = now + timedelta(seconds=min(2**record.attempts, 30))
                event_type = AgentJobEventType.RETRY_SCHEDULED
            else:
                record.status = AgentJobStatus.DEAD_LETTER
                record.finished_at = now
                event_type = AgentJobEventType.DEAD_LETTERED
            self._event(session, record, event_type, {"classification": classification[:100]})
            return record.status

    def recover_expired_leases(self) -> int:
        now = self.clock()
        recovered = 0
        with self.session_factory.begin() as session:
            records = session.scalars(
                select(AgentWorkflowJobRecord)
                .where(
                    AgentWorkflowJobRecord.status == AgentJobStatus.RUNNING,
                    AgentWorkflowJobRecord.lease_expires_at < now,
                )
                .with_for_update(skip_locked=True)
            ).all()
            for record in records:
                record.worker_id = None
                record.lease_expires_at = None
                record.error_classification = "worker_lease_expired"
                if record.attempts < record.max_attempts:
                    record.status = AgentJobStatus.RETRYING
                    record.available_at = now
                    event_type = AgentJobEventType.RETRY_SCHEDULED
                else:
                    record.status = AgentJobStatus.DEAD_LETTER
                    record.finished_at = now
                    event_type = AgentJobEventType.DEAD_LETTERED
                self._event(session, record, event_type, {"classification": "lease_expired"})
                recovered += 1
        return recovered

    def get(self, job_id: str, tenant_id: str) -> AgentWorkflowJob | None:
        with self.session_factory() as session:
            record = session.scalar(
                select(AgentWorkflowJobRecord).where(
                    AgentWorkflowJobRecord.job_id == job_id,
                    AgentWorkflowJobRecord.tenant_id == tenant_id,
                )
            )
            return None if record is None else self._model(record)

    def events_after(self, job_id: str, tenant_id: str, after: int = 0) -> list[AgentJobEvent]:
        with self.session_factory() as session:
            records = session.scalars(
                select(AgentJobEventRecord)
                .where(
                    AgentJobEventRecord.job_id == job_id,
                    AgentJobEventRecord.tenant_id == tenant_id,
                    AgentJobEventRecord.event_id > after,
                )
                .order_by(AgentJobEventRecord.event_id)
            ).all()
            return [self._event_model(record) for record in records]

    def health(self) -> QueueHealth:
        with self.session_factory() as session:
            counts = dict(
                session.execute(
                    select(AgentWorkflowJobRecord.status, func.count()).group_by(
                        AgentWorkflowJobRecord.status
                    )
                ).all()
            )
        pending = int(counts.get(AgentJobStatus.PENDING, 0))
        retrying = int(counts.get(AgentJobStatus.RETRYING, 0))
        running = int(counts.get(AgentJobStatus.RUNNING, 0))
        return QueueHealth(
            pending=pending,
            running=running,
            retrying=retrying,
            dead_letter=int(counts.get(AgentJobStatus.DEAD_LETTER, 0)),
            capacity=self.capacity,
            accepting=pending + retrying + running < self.capacity,
        )

    @staticmethod
    def _owned_running(session: Session, job_id: str, worker_id: str) -> AgentWorkflowJobRecord:
        record = session.get(AgentWorkflowJobRecord, job_id, with_for_update=True)
        if (
            record is None
            or record.status != AgentJobStatus.RUNNING
            or record.worker_id != worker_id
        ):
            raise ValueError("job is not owned by this worker")
        return record

    def _event(
        self,
        session: Session,
        job: AgentWorkflowJobRecord,
        event_type: AgentJobEventType,
        details: dict[str, str] | None = None,
    ) -> None:
        session.add(
            AgentJobEventRecord(
                job_id=job.job_id,
                tenant_id=job.tenant_id,
                event_type=event_type,
                status=job.status,
                occurred_at=self.clock(),
                details=details or {},
            )
        )

    @staticmethod
    def _model(record: AgentWorkflowJobRecord) -> AgentWorkflowJob:
        return AgentWorkflowJob(
            job_id=record.job_id,
            tenant_id=record.tenant_id,
            workflow_id=record.workflow_id,
            case_id=record.case_id,
            domain=record.domain,
            objective=record.objective,
            status=record.status,
            attempts=record.attempts,
            max_attempts=record.max_attempts,
            created_at=record.created_at,
            available_at=record.available_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
            lease_expires_at=record.lease_expires_at,
            worker_id=record.worker_id,
            result=(
                MultiAgentReasoningResult.model_validate(record.result)
                if record.result is not None
                else None
            ),
            error_classification=record.error_classification,
        )

    @staticmethod
    def _event_model(record: AgentJobEventRecord) -> AgentJobEvent:
        return AgentJobEvent(
            event_id=record.event_id,
            job_id=record.job_id,
            tenant_id=record.tenant_id,
            event_type=record.event_type,
            status=record.status,
            occurred_at=record.occurred_at,
            details=record.details,
        )
