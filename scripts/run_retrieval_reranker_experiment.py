import argparse
import hashlib
import json
import platform
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from time import perf_counter

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from resolveops.database.base import Base
from resolveops.database.session import create_session_factory
from resolveops.knowledge.embeddings import FastEmbedProvider
from resolveops.knowledge.evaluate import DEFAULT_DATASET, DEFAULT_POLICY_DIRECTORY
from resolveops.knowledge.evaluation import evaluate_retriever, load_evaluation_cases
from resolveops.knowledge.ingestion import ingest_directory
from resolveops.knowledge.models import RetrievalMethod
from resolveops.knowledge.reranking import (
    FastEmbedCrossEncoderReranker,
    RerankedPolicyRetriever,
)
from resolveops.knowledge.retrieval import HybridPolicyRetriever


class TimedRetriever:
    def __init__(self, retriever):  # type: ignore[no-untyped-def]
        self.retriever = retriever
        self.latencies_ms: list[float] = []

    def search(self, query, *, as_of, issue_type=None, top_k=5):  # type: ignore[no-untyped-def]
        started = perf_counter()
        result = self.retriever.search(query, as_of=as_of, issue_type=issue_type, top_k=top_k)
        self.latencies_ms.append((perf_counter() - started) * 1_000)
        return result


def _latency(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {
        "samples": len(ordered),
        "p50": ordered[max(ceil(0.50 * len(ordered)) - 1, 0)],
        "p95": ordered[max(ceil(0.95 * len(ordered)) - 1, 0)],
        "maximum": ordered[-1],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare hybrid retrieval with cross-encoder reranking"
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--policies", type=Path, default=DEFAULT_POLICY_DIRECTORY)
    parser.add_argument("--output", type=Path, default=Path("evals/retrieval/reranker-report.json"))
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--candidate-pool", type=int, default=20)
    parser.add_argument("--embedding-model", default="BAAI/bge-small-en-v1.5")
    parser.add_argument("--reranker-model", default="Xenova/ms-marco-MiniLM-L-6-v2")
    args = parser.parse_args()

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    provider = FastEmbedProvider(model_name=args.embedding_model, dimensions=384)
    as_of = datetime.now(UTC)
    with factory.begin() as session:
        ingestion = ingest_directory(session, args.policies, provider, ingested_at=as_of)
    cases = load_evaluation_cases(args.dataset)
    reranker = FastEmbedCrossEncoderReranker(args.reranker_model)
    with factory() as session:
        base = TimedRetriever(HybridPolicyRetriever(session, provider))
        base_metrics = evaluate_retriever(
            base, RetrievalMethod.HYBRID, cases, as_of=as_of, k=args.k
        )
        reranked = TimedRetriever(
            RerankedPolicyRetriever(
                HybridPolicyRetriever(session, provider),
                reranker,
                candidate_pool=args.candidate_pool,
            )
        )
        reranked_metrics = evaluate_retriever(
            reranked, RetrievalMethod.HYBRID, cases, as_of=as_of, k=args.k
        )

    base_latency = _latency(base.latencies_ms)
    reranked_latency = _latency(reranked.latencies_ms)
    adopt = (
        reranked_metrics.mrr >= base_metrics.mrr + 0.01
        and reranked_metrics.ndcg_at_k >= base_metrics.ndcg_at_k
        and float(reranked_latency["p95"]) <= 250
    )
    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "operating_system": platform.system(),
            "database": "SQLite in-memory",
        },
        "dataset": args.dataset.as_posix(),
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "query_count": len(cases),
        "policy_documents": ingestion.discovered_documents,
        "policy_chunks": ingestion.created_chunks,
        "embedding_model": args.embedding_model,
        "reranker_model": args.reranker_model,
        "candidate_pool": args.candidate_pool,
        "k": args.k,
        "hybrid": {
            "metrics": base_metrics.model_dump(mode="json"),
            "latency_ms": base_latency,
        },
        "hybrid_reranked": {
            "metrics": reranked_metrics.model_dump(mode="json"),
            "latency_ms": reranked_latency,
        },
        "adoption_rule": "MRR improves by at least 0.01, nDCG does not regress, and local p95 is at most 250 ms",
        "adopt_reranker": adopt,
        "decision": (
            "adopt behind an independent feature flag"
            if adopt
            else "do not adopt; retain measured hybrid baseline"
        ),
        "limitations": [
            "This local experiment uses six policy documents and cannot establish production quality.",
            "Latency includes local ONNX inference and excludes network, API, and concurrent load.",
            "Labels are hand-authored synthetic relevance judgments, not human production feedback.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
