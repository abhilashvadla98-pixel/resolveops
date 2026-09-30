import json
import platform
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import monotonic
from uuid import uuid4

from sqlalchemy import delete

from resolveops.agents.models import AgentDomain
from resolveops.database.job_records import AgentJobEventRecord, AgentWorkflowJobRecord
from resolveops.database.session import create_database_engine, create_session_factory
from resolveops.jobs.store import AgentJobStore


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return round(ordered[max(round(len(ordered) * fraction + 0.499999) - 1, 0)], 3)


def main() -> int:
    parser = ArgumentParser(description="Measure durable multi-worker queue claims.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--jobs", type=int, default=100)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("benchmarks/results/agent-queue.json"),
    )
    args = parser.parse_args()
    if not 10 <= args.jobs <= 10_000:
        raise ValueError("jobs must be between 10 and 10000")
    if not 2 <= args.workers <= 64:
        raise ValueError("workers must be between 2 and 64")

    engine = create_database_engine(args.database_url)
    factory = create_session_factory(engine)
    store = AgentJobStore(factory, capacity=args.jobs + 10)
    run_id = uuid4().hex[:12]
    job_ids = []
    enqueue_started = monotonic()
    for index in range(args.jobs):
        job = store.enqueue(
            tenant_id="TENANT-BENCHMARK",
            workflow_id=f"WF-BENCH-{run_id}-{index}",
            case_id=f"CASE-BENCH-{index}",
            domain=AgentDomain.CUSTOMER_OPERATIONS,
            objective="Benchmark durable queue claiming without invoking a model.",
            idempotency_key=f"QUEUE-BENCH-{run_id}-{index}",
        )
        job_ids.append(job.job_id)
    enqueue_seconds = monotonic() - enqueue_started

    claim_latencies: list[float] = []

    def claim(worker_number: int) -> list[str]:
        claimed = []
        while True:
            started = monotonic()
            job = store.claim_next(f"BENCH-WORKER-{worker_number}")
            claim_latencies.append((monotonic() - started) * 1000)
            if job is None:
                return claimed
            claimed.append(job.job_id)

    claim_started = monotonic()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        claims = [
            job_id for result in executor.map(claim, range(args.workers)) for job_id in result
        ]
    claim_seconds = monotonic() - claim_started
    claimed_set = set(claims)
    duplicate_claims = len(claims) - len(claimed_set)
    missing_claims = sorted(set(job_ids) - claimed_set)
    health = store.health()
    successful = duplicate_claims == 0 and not missing_claims and health.running == args.jobs
    report = {
        "measured": True,
        "measured_at": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "operating_system": platform.system(),
            "database": engine.dialect.name,
        },
        "jobs": args.jobs,
        "workers": args.workers,
        "enqueue_seconds": round(enqueue_seconds, 3),
        "enqueue_jobs_per_second": round(args.jobs / enqueue_seconds, 3),
        "claim_seconds": round(claim_seconds, 3),
        "claim_jobs_per_second": round(args.jobs / claim_seconds, 3),
        "claim_latency_p50_ms": round(median(claim_latencies), 3),
        "claim_latency_p95_ms": percentile(claim_latencies, 0.95),
        "claimed_count": len(claims),
        "duplicate_claims": duplicate_claims,
        "missing_claims": missing_claims,
        "queue_health_after_claims": health.model_dump(mode="json"),
        "passed": successful,
        "limitations": [
            "The benchmark measures durable claim coordination, not model-provider throughput.",
            "Claimed benchmark jobs are removed after measurement instead of invoking paid models.",
            "Results from one developer machine are not a production capacity guarantee.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with factory.begin() as session:
        session.execute(delete(AgentJobEventRecord).where(AgentJobEventRecord.job_id.in_(job_ids)))
        session.execute(
            delete(AgentWorkflowJobRecord).where(AgentWorkflowJobRecord.job_id.in_(job_ids))
        )
    engine.dispose()
    print(
        f"Claimed {len(claims)}/{args.jobs} jobs with {duplicate_claims} duplicates; "
        f"report={args.output}"
    )
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
