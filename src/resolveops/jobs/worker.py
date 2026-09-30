from __future__ import annotations

import logging
import socket
from uuid import uuid4

from resolveops.agents.budgets import AgentBudgetExceeded
from resolveops.agents.factory import build_agent_runtime
from resolveops.config import get_settings
from resolveops.database.session import create_database_engine, create_session_factory
from resolveops.jobs.coordination import build_wakeup_channel
from resolveops.jobs.store import AgentJobStore
from resolveops.orchestration.graph import HierarchicalAgentOrchestrator
from resolveops.reasoning.errors import ReasoningProviderError

LOGGER = logging.getLogger(__name__)


def process_one(store: AgentJobStore, worker_id: str) -> bool:
    job = store.claim_next(worker_id)
    if job is None:
        return False
    settings = get_settings()
    try:
        runtime = build_agent_runtime(
            store.session_factory,
            settings,
            tenant_id=job.tenant_id,
            on_status=lambda run: store.record_agent_progress(job.job_id, worker_id, run),
        )
        result = HierarchicalAgentOrchestrator(runtime).run(
            workflow_id=job.workflow_id,
            case_id=job.case_id,
            tenant_id=job.tenant_id,
            domain=job.domain,
            objective=job.objective,
            trace_id=uuid4().hex,
        )
        store.complete(job.job_id, worker_id, result)
    except AgentBudgetExceeded:
        store.fail(job.job_id, worker_id, "agent_budget_exceeded")
    except ReasoningProviderError as exc:
        store.fail(job.job_id, worker_id, f"provider_{exc.code}")
    except Exception:
        LOGGER.exception("agent job failed", extra={"job_id": job.job_id})
        store.fail(job.job_id, worker_id, "unexpected_worker_error")
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    factory = create_session_factory(create_database_engine(settings.resolved_database_url()))
    store = AgentJobStore(
        factory,
        capacity=settings.agent_queue_capacity,
        lease_seconds=settings.agent_job_lease_seconds,
    )
    channel = build_wakeup_channel(settings.redis_url)
    worker_id = f"{socket.gethostname()}-{uuid4().hex[:8]}"
    LOGGER.info("agent worker started", extra={"worker_id": worker_id})
    while True:
        store.recover_expired_leases()
        if not process_one(store, worker_id):
            channel.wait(settings.agent_worker_poll_seconds)


if __name__ == "__main__":
    main()
