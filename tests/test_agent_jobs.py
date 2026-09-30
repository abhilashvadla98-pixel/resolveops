from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from resolveops.agents.models import (
    AgentDomain,
    AgentInvocationRecord,
    AgentRole,
    AgentRunStatus,
)
from resolveops.database.base import Base
from resolveops.database.session import create_session_factory
from resolveops.jobs.models import AgentJobEventType, AgentJobStatus
from resolveops.jobs.store import AgentJobStore, QueueCapacityExceeded


def job_store(now: list[datetime], *, capacity: int = 10, lease_seconds: int = 30) -> AgentJobStore:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return AgentJobStore(
        create_session_factory(engine),
        capacity=capacity,
        lease_seconds=lease_seconds,
        clock=lambda: now[0],
    )


def enqueue(store: AgentJobStore, *, key: str = "KEY-1", tenant: str = "TENANT-A"):
    return store.enqueue(
        tenant_id=tenant,
        workflow_id=f"WF-{key}",
        case_id="CASE-1001",
        domain=AgentDomain.CUSTOMER_OPERATIONS,
        objective="Investigate the persisted case safely.",
        idempotency_key=key,
        max_attempts=2,
    )


def test_enqueue_is_tenant_idempotent_and_enforces_backpressure() -> None:
    now = [datetime(2026, 9, 29, 20, 0, tzinfo=UTC)]
    store = job_store(now, capacity=2)

    first = enqueue(store)
    replay = enqueue(store)
    other_tenant = enqueue(store, tenant="TENANT-B")

    assert replay.job_id == first.job_id
    assert other_tenant.job_id != first.job_id
    assert store.health().accepting is False
    with pytest.raises(QueueCapacityExceeded):
        enqueue(store, key="KEY-2")


def test_worker_claim_retry_dead_letter_and_events_are_durable() -> None:
    now = [datetime(2026, 9, 29, 20, 0, tzinfo=UTC)]
    store = job_store(now)
    queued = enqueue(store)

    claimed = store.claim_next("WORKER-A")
    assert claimed is not None
    assert claimed.status == AgentJobStatus.RUNNING
    assert claimed.attempts == 1
    assert store.fail(claimed.job_id, "WORKER-A", "provider_timeout") == AgentJobStatus.RETRYING

    now[0] += timedelta(seconds=3)
    retried = store.claim_next("WORKER-B")
    assert retried is not None
    assert retried.attempts == 2
    assert store.fail(retried.job_id, "WORKER-B", "provider_timeout") == AgentJobStatus.DEAD_LETTER

    saved = store.get(queued.job_id, "TENANT-A")
    assert saved is not None
    assert saved.status == AgentJobStatus.DEAD_LETTER
    assert store.get(queued.job_id, "TENANT-OTHER") is None
    assert [event.event_type for event in store.events_after(queued.job_id, "TENANT-A")] == [
        AgentJobEventType.QUEUED,
        AgentJobEventType.CLAIMED,
        AgentJobEventType.RETRY_SCHEDULED,
        AgentJobEventType.CLAIMED,
        AgentJobEventType.DEAD_LETTERED,
    ]


def test_expired_worker_lease_is_recovered_without_duplicate_ownership() -> None:
    now = [datetime(2026, 9, 29, 20, 0, tzinfo=UTC)]
    store = job_store(now, lease_seconds=30)
    enqueue(store)
    claimed = store.claim_next("FAILED-WORKER")
    assert claimed is not None

    now[0] += timedelta(seconds=31)
    assert store.recover_expired_leases() == 1
    reclaimed = store.claim_next("RECOVERY-WORKER")

    assert reclaimed is not None
    assert reclaimed.worker_id == "RECOVERY-WORKER"
    assert reclaimed.attempts == 2


def test_agent_role_progress_is_projected_without_reasoning_content() -> None:
    now = [datetime(2026, 9, 29, 20, 0, tzinfo=UTC)]
    store = job_store(now)
    queued = enqueue(store)
    claimed = store.claim_next("WORKER-A")
    assert claimed is not None
    run = AgentInvocationRecord(
        agent_run_id="ARUN-SUPERVISOR-1",
        workflow_id=queued.workflow_id,
        tenant_id=queued.tenant_id,
        role=AgentRole.SUPERVISOR,
        prompt_version="supervisor-v1",
        schema_version="supervisor-v1",
        provider="synthetic",
        model="synthetic",
        started_at=now[0],
        status=AgentRunStatus.RUNNING,
        context_hash="0" * 64,
        trace_id="TRACE-1",
    )

    store.record_agent_progress(queued.job_id, "WORKER-A", run)

    progress = store.events_after(queued.job_id, queued.tenant_id)[-1]
    assert progress.event_type == AgentJobEventType.AGENT_STARTED
    assert progress.details == {
        "role": "supervisor",
        "agent_run_id": "ARUN-SUPERVISOR-1",
    }
