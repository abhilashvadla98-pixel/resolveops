import json
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
    route: str
    status: int
    latency_ms: float


def request(base_url: str, token: str, route: str) -> Sample:
    started = monotonic()
    status = 0
    try:
        response = urlopen(
            Request(
                base_url + route,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            ),
            timeout=10,
        )
        status = response.status
        response.read()
    except HTTPError as exc:
        status = exc.code
    except (URLError, TimeoutError):
        status = 0
    return Sample(route, status, (monotonic() - started) * 1000)


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
    parser.add_argument("--output", type=Path, default=Path("benchmarks/results/load-latest.json"))
    args = parser.parse_args()
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

    def worker() -> None:
        local: list[Sample] = []
        while monotonic() < deadline:
            local.append(request(args.base_url.rstrip("/"), args.token, rng.choice(routes)))
            if args.target_rps:
                sleep(args.concurrency / args.target_rps)
        with lock:
            samples.extend(local)

    started = monotonic()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(worker) for _ in range(args.concurrency)]
        for future in futures:
            future.result()
    elapsed = monotonic() - started
    latencies = [item.latency_ms for item in samples]
    errors = [item for item in samples if not 200 <= item.status < 400]
    route_results = {}
    for route in routes:
        route_samples = [item for item in samples if item.route == route]
        route_latencies = [item.latency_ms for item in route_samples]
        route_results[route] = {
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
        "mode": "bounded_read_only_soak",
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
        "limitations": [
            "Mutation endpoints are excluded to protect shared demo state.",
            "Client-side resource measurements do not include server CPU or memory.",
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
