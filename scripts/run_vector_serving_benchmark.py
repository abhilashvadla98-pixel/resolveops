import argparse
import json
import math
import platform
from datetime import UTC, datetime
from math import ceil
from pathlib import Path
from time import perf_counter

import psycopg
from psycopg import sql

from resolveops.knowledge.vector_index import ExactVectorIndex, VectorEntry


def _vector(record_id: int, dimensions: int) -> list[float]:
    values = [
        (((record_id + 1) * (position + 3)) % 101 - 50) / 50 for position in range(dimensions)
    ]
    values[record_id % dimensions] += 1.0
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values]


def _literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.9f}" for value in vector) + "]"


def _distribution(samples: list[float]) -> dict[str, float | int]:
    ordered = sorted(samples)
    return {
        "samples": len(ordered),
        "minimum": ordered[0],
        "p50": ordered[max(ceil(0.50 * len(ordered)) - 1, 0)],
        "p95": ordered[max(ceil(0.95 * len(ordered)) - 1, 0)],
        "maximum": ordered[-1],
    }


def _benchmark_size(
    connection: psycopg.Connection[tuple[object, ...]],
    *,
    size: int,
    dimensions: int,
    query_count: int,
    top_k: int,
) -> dict[str, object]:
    entries = [
        VectorEntry(entry_id=f"VEC-{index:07d}", vector=_vector(index, dimensions))
        for index in range(size)
    ]
    with connection.cursor() as cursor:
        cursor.execute("TRUNCATE vector_benchmark")
        cursor.executemany(
            "INSERT INTO vector_benchmark (entry_id, embedding) VALUES (%s, %s::vector)",
            [(entry.entry_id, _literal(entry.vector)) for entry in entries],
        )
    connection.commit()

    started = perf_counter()
    python_index = ExactVectorIndex(entries, dimensions=dimensions)
    python_build_ms = (perf_counter() - started) * 1_000
    query_indexes = [
        round(index * (size - 1) / max(query_count - 1, 1)) for index in range(query_count)
    ]
    python_latencies: list[float] = []
    postgres_latencies: list[float] = []
    recalls: list[float] = []
    for query_index in query_indexes:
        query = entries[query_index].vector
        started = perf_counter()
        expected = [item[0] for item in python_index.search(query, top_k=top_k)]
        python_latencies.append((perf_counter() - started) * 1_000)
        started = perf_counter()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT entry_id FROM vector_benchmark ORDER BY embedding <=> %s::vector, entry_id LIMIT %s",
                (_literal(query), top_k),
            )
            actual = [str(row[0]) for row in cursor.fetchall()]
        postgres_latencies.append((perf_counter() - started) * 1_000)
        recalls.append(len(set(expected).intersection(actual)) / top_k)
    return {
        "vector_count": size,
        "dimensions": dimensions,
        "query_count": query_count,
        "top_k": top_k,
        "python_exact_build_ms": python_build_ms,
        "python_exact_latency_ms": _distribution(python_latencies),
        "pgvector_exact_latency_ms": _distribution(postgres_latencies),
        "pgvector_recall_against_python_exact": sum(recalls) / len(recalls),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare Python exact vectors with pgvector exact serving"
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--sizes", nargs="+", type=int, default=[1000, 10000])
    parser.add_argument("--dimensions", type=int, default=64)
    parser.add_argument("--queries", type=int, default=12)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument(
        "--output", type=Path, default=Path("benchmarks/results/vector-serving.json")
    )
    args = parser.parse_args()
    if any(size < 100 for size in args.sizes):
        raise ValueError("benchmark sizes must be at least 100 vectors")
    if not 8 <= args.dimensions <= 2_000:
        raise ValueError("benchmark dimensions must be between 8 and 2000")

    with psycopg.connect(args.database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cursor.execute("DROP TABLE IF EXISTS vector_benchmark")
            cursor.execute(
                sql.SQL(
                    "CREATE UNLOGGED TABLE vector_benchmark "
                    "(entry_id text PRIMARY KEY, embedding vector({}) NOT NULL)"
                ).format(sql.SQL(str(args.dimensions)))
            )
        connection.commit()
        points = [
            _benchmark_size(
                connection,
                size=size,
                dimensions=args.dimensions,
                query_count=args.queries,
                top_k=args.k,
            )
            for size in args.sizes
        ]
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE vector_benchmark")
        connection.commit()

    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "operating_system": platform.system(),
            "database": "disposable pgvector/pgvector:pg16 container",
        },
        "method": "exact cosine scan in both implementations; no approximate index",
        "points": points,
        "decision": "retain Python exact retrieval for the current 17-chunk corpus; pgvector is deployable when measured corpus growth justifies it",
        "limitations": [
            "Synthetic deterministic vectors measure serving mechanics, not policy retrieval quality.",
            "This single-client local benchmark is not a concurrency or production-capacity test.",
            "The application schema was not changed because the current policy corpus is only 17 chunks.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
