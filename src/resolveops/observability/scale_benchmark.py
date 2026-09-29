import json
import platform
import tempfile
import tracemalloc
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter, process_time
from typing import Any

from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session, selectinload

from resolveops.data_generation.generator import generate_dataset
from resolveops.data_generation.loader import load_dataset
from resolveops.data_generation.profiles import get_profile
from resolveops.database.action_records import AuditEventRecord
from resolveops.database.base import Base
from resolveops.database.knowledge_records import KnowledgeDocumentRecord
from resolveops.database.records import CaseIssueRecord, CaseRecord, PaymentRecord
from resolveops.database.workflow_records import WorkflowRunRecord
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.knowledge.ingestion import ingest_directory
from resolveops.knowledge.retrieval import HybridPolicyRetriever
from resolveops.models.case import CaseIssueType


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = max(round(len(ordered) * fraction + 0.499999) - 1, 0)
    return round(ordered[index], 3)


def measure(operation: Callable[[], object], *, samples: int) -> dict[str, float]:
    values: list[float] = []
    operation()
    for _ in range(samples):
        started = perf_counter()
        operation()
        values.append((perf_counter() - started) * 1000)
    return {
        "p50_ms": round(median(values), 3),
        "p95_ms": percentile(values, 0.95),
        "max_ms": round(max(values), 3),
    }


def _database_size(engine: Engine) -> int | None:
    if engine.dialect.name != "postgresql":
        return None
    with engine.connect() as connection:
        return int(connection.scalar(text("SELECT pg_database_size(current_database())")) or 0)


def _query_metrics(
    engine: Engine, *, samples: int, case_id: str, order_id: str
) -> dict[str, dict[str, float]]:
    def run(statement: Any) -> object:
        with Session(engine) as session:
            return session.execute(statement).all()

    metrics = {
        "case_list": measure(
            lambda: run(
                select(CaseRecord.case_id, CaseRecord.status, CaseRecord.updated_at)
                .order_by(CaseRecord.updated_at.desc())
                .limit(25)
            ),
            samples=samples,
        ),
        "case_detail": measure(
            lambda: run(
                select(CaseRecord)
                .options(selectinload(CaseRecord.issues).selectinload(CaseIssueRecord.evidence))
                .where(CaseRecord.case_id == case_id)
            ),
            samples=samples,
        ),
        "payment_lookup": measure(
            lambda: run(select(PaymentRecord).where(PaymentRecord.order_id == order_id)),
            samples=samples,
        ),
        "audit_timeline": measure(
            lambda: run(
                select(AuditEventRecord)
                .where(AuditEventRecord.case_id == case_id)
                .order_by(AuditEventRecord.occurred_at)
            ),
            samples=samples,
        ),
        "workflow_lookup": measure(
            lambda: run(select(WorkflowRunRecord).where(WorkflowRunRecord.case_id == case_id)),
            samples=samples,
        ),
    }
    provider = FeatureHashEmbeddingProvider(dimensions=128)
    with Session(engine) as session:
        retriever = HybridPolicyRetriever(session, provider)
        metrics["hybrid_retrieval"] = measure(
            lambda: retriever.search(
                "duplicate captured payment refund policy",
                as_of=datetime.now(UTC),
                issue_type=CaseIssueType.DUPLICATE_CHARGE,
                top_k=3,
            ),
            samples=samples,
        )
    return metrics


def run_scale_benchmark(
    engine: Engine,
    *,
    customer_case_sizes: list[int],
    it_ratio: float,
    samples: int,
    seed: int,
    repository_root: Path,
) -> dict[str, object]:
    database_name = engine.url.database or ""
    if engine.dialect.name != "postgresql" or "benchmark" not in database_name.lower():
        raise ValueError(
            "scale benchmark requires an isolated PostgreSQL database with 'benchmark' in its name"
        )
    results: list[dict[str, object]] = []
    tracemalloc.start()
    cpu_started = process_time()
    with tempfile.TemporaryDirectory(prefix="resolveops-scale-") as temporary:
        root = Path(temporary)
        for customer_cases in customer_case_sizes:
            it_requests = max(round(customer_cases * it_ratio), 1)
            dataset_dir = root / f"cases-{customer_cases}"
            profile = get_profile("demo").with_overrides(
                customer_cases=customer_cases, it_requests=it_requests, seed=seed
            )
            generation_started = perf_counter()
            manifest = generate_dataset(dataset_dir, profile, version="benchmark-1")
            generation_seconds = perf_counter() - generation_started
            Base.metadata.drop_all(engine)
            Base.metadata.create_all(engine)
            load_started = perf_counter()
            with Session(engine) as session:
                loaded = load_dataset(session, dataset_dir, batch_size=1_000)
            load_seconds = perf_counter() - load_started
            with Session(engine) as session:
                ingest_directory(
                    session,
                    repository_root / "domain_packs",
                    FeatureHashEmbeddingProvider(dimensions=128),
                    ingested_at=datetime.now(UTC),
                )
                session.commit()
                knowledge_documents = (
                    session.scalar(select(func.count()).select_from(KnowledgeDocumentRecord)) or 0
                )
            metrics = _query_metrics(
                engine, samples=samples, case_id="CASE-000001", order_id="ORD-000001"
            )
            results.append(
                {
                    "customer_cases": customer_cases,
                    "it_requests": it_requests,
                    "generated_records": manifest.total_records,
                    "manifest_files": manifest.files,
                    "loaded_records": sum(loaded.values()),
                    "generation_seconds": round(generation_seconds, 3),
                    "load_seconds": round(load_seconds, 3),
                    "database_bytes": _database_size(engine),
                    "knowledge_documents": knowledge_documents,
                    "query_latency": metrics,
                }
            )
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "benchmark_id": f"scale-{datetime.now(UTC):%Y%m%dT%H%M%SZ}",
        "measured_at": datetime.now(UTC).isoformat(),
        "database": "PostgreSQL isolated benchmark database",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "seed": seed,
        "samples_per_query": samples,
        "results": results,
        "runner_cpu_seconds": round(process_time() - cpu_started, 3),
        "runner_peak_traced_memory_bytes": peak,
        "limitations": [
            "Runner memory excludes PostgreSQL server memory.",
            "Direct query latency is not end-to-end HTTP latency.",
            "Synthetic benchmark results do not establish production capacity.",
        ],
    }


def save_scale_report(report: dict[str, object], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
