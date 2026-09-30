import json
import os
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from random import Random
from statistics import median
from threading import Lock
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Sample:
    method: str
    route: str
    status: int
    latency_ms: float


def request(
    base_url: str,
    token: str,
    route: str,
    *,
    method: str = "GET",
    body: dict[str, str] | None = None,
) -> Sample:
    started = monotonic()
    status = 0
    try:
        encoded = None if body is None else json.dumps(body).encode("utf-8")
        response = urlopen(
            Request(
                base_url + route,
                data=encoded,
                method=method,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            ),
            timeout=10,
        )
        status = response.status
        response.read()
    except HTTPError as exc:
        status = exc.code
    except (URLError, TimeoutError):
        status = 0
    return Sample(method, route, status, (monotonic() - started) * 1000)


def process_rss_bytes(pid: int | None) -> int | None:
    if pid is None:
        return None
    try:
        import psutil

        return int(psutil.Process(pid).memory_info().rss)
    except (ImportError, psutil.Error):
        return None


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return round(ordered[max(round(len(ordered) * fraction + 0.499999) - 1, 0)], 3)


def main() -> int:
    parser = ArgumentParser(description="Run a bounded read-only ResolveOps API load/soak test.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", required=True, help="Restricted demo or test token")
    parser.add_argument("--duration-seconds", type=int, default=60)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--target-rps",
        type=float,
        help="Optional total request-rate ceiling across all workers.",
    )
    parser.add_argument("--case-id", default="CASE-1001")
    parser.add_argument("--workflow-id")
    parser.add_argument(
        "--mutation-percent",
        type=int,
        default=0,
        help="Percentage of requests that create a case; use only with isolated/resettable data.",
    )
    parser.add_argument("--customer-id", default="CUSTOMER-1001")
    parser.add_argument("--order-id", default="ORDER-1001")
    parser.add_argument(
        "--server-pid",
        type=int,
        help="Optional server PID used to sample RSS before and after the bounded run.",
    )
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/load-latest.json"))
    args = parser.parse_args()
    if not 0 <= args.mutation_percent <= 50:
        raise ValueError("mutation-percent must be between 0 and 50")
    routes = [
        "/api/v1/case-queue?page_size=25",
        f"/api/v1/cases/{args.case_id}",
        f"/api/v1/cases/{args.case_id}/timeline",
        "/api/v1/approvals",
        "/api/v1/audit/events?limit=50",
        "/api/v1/reliability/summary",
        "/api/v1/it/cases?page_size=25",
    ]
    if args.workflow_id:
        routes.append(f"/api/v1/workflows/{args.workflow_id}")
    deadline = monotonic() + args.duration_seconds
    samples: list[Sample] = []
    lock = Lock()
    rng = Random(20260929)
    rss_before = process_rss_bytes(args.server_pid)

    def worker(worker_number: int) -> None:
        local: list[Sample] = []
        local_rng = Random(20260929 + os.getpid() + worker_number)
        while monotonic() < deadline:
            if args.mutation_percent and local_rng.randrange(100) < args.mutation_percent:
                local.append(
                    request(
                        args.base_url.rstrip("/"),
                        args.token,
                        "/api/v1/cases",
                        method="POST",
                        body={
                            "customer_id": args.customer_id,
                            "order_id": args.order_id,
                            "complaint": "I was charged twice for this order.",
                        },
                    )
                )
            else:
                local.append(request(args.base_url.rstrip("/"), args.token, rng.choice(routes)))
            if args.target_rps:
                sleep(args.concurrency / args.target_rps)
        with lock:
            samples.extend(local)

    started = monotonic()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(worker, index) for index in range(args.concurrency)]
        for future in futures:
            future.result()
    elapsed = monotonic() - started
    rss_after = process_rss_bytes(args.server_pid)
    latencies = [item.latency_ms for item in samples]
    errors = [item for item in samples if not 200 <= item.status < 400]
    route_results = {}
    operation_names = [("GET", route) for route in routes]
    if args.mutation_percent:
        operation_names.append(("POST", "/api/v1/cases"))
    for method, route in operation_names:
        route_samples = [item for item in samples if item.route == route and item.method == method]
        route_latencies = [item.latency_ms for item in route_samples]
        route_results[f"{method} {route}"] = {
            "requests": len(route_samples),
            "errors": sum(not 200 <= item.status < 400 for item in route_samples),
            "p50_ms": percentile(route_latencies, 0.5) if route_latencies else None,
            "p95_ms": percentile(route_latencies, 0.95) if route_latencies else None,
        }
    status_counts: dict[str, int] = {}
    for sample in samples:
        key = str(sample.status)
        status_counts[key] = status_counts.get(key, 0) + 1
    report = {
        "measured": True,
        "mode": (
            "bounded_mixed_read_write_soak" if args.mutation_percent else "bounded_read_only_soak"
        ),
        "mutation_percent": args.mutation_percent,
        "observed_mutation_percent": round(
            100 * sum(item.method == "POST" for item in samples) / len(samples), 3
        ),
        "duration_seconds": round(elapsed, 3),
        "concurrency": args.concurrency,
        "target_rps": args.target_rps,
        "requests": len(samples),
        "requests_per_second": round(len(samples) / elapsed, 3),
        "error_count": len(errors),
        "error_rate": round(len(errors) / len(samples), 6) if samples else 0,
        "status_counts": status_counts,
        "p50_ms": round(median(latencies), 3) if latencies else None,
        "p95_ms": percentile(latencies, 0.95) if latencies else None,
        "routes": route_results,
        "server_rss_bytes_before": rss_before,
        "server_rss_bytes_after": rss_after,
        "server_rss_growth_bytes": (
            None if rss_before is None or rss_after is None else rss_after - rss_before
        ),
        "limitations": [
            (
                "Mutation traffic was limited to case intake against isolated/resettable data."
                if args.mutation_percent
                else "Mutation endpoints were excluded to protect shared demo state."
            ),
            (
                "Server RSS is a start/end signal, not a leak proof or full CPU/memory profile."
                if args.server_pid
                else "Server memory was not sampled because no server PID was supplied."
            ),
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Measured {len(samples)} requests in {elapsed:.2f}s; errors={len(errors)}; report={args.output}"
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
