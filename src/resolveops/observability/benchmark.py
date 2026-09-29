import argparse
import hashlib
import json
import platform
from datetime import UTC, datetime
from pathlib import Path

from resolveops.evaluation.dataset import load_workflow_evaluation_cases
from resolveops.evaluation.workflow import evaluate_workflow_cases
from resolveops.observability.metrics import summarize_trace_events
from resolveops.observability.models import PerformanceReport
from resolveops.observability.sinks import InMemoryTraceSink

DEFAULT_DATASET = Path("evals/workflows/customer_operations.jsonl")


def measure_workflow_performance(
    dataset: Path,
    *,
    warmup_runs: int = 1,
    measured_runs: int = 3,
) -> PerformanceReport:
    if not 0 <= warmup_runs <= 10:
        raise ValueError("warmup_runs must be between 0 and 10")
    if not 1 <= measured_runs <= 20:
        raise ValueError("measured_runs must be between 1 and 20")
    cases = load_workflow_evaluation_cases(dataset)
    for _ in range(warmup_runs):
        evaluate_workflow_cases(
            cases,
            dataset_name=dataset.as_posix(),
            observability_sink=InMemoryTraceSink(),
        )

    sink = InMemoryTraceSink()
    passed = 0
    failed = 0
    for _ in range(measured_runs):
        evaluation = evaluate_workflow_cases(
            cases,
            dataset_name=dataset.as_posix(),
            observability_sink=sink,
        )
        passed += evaluation.passed_count
        failed += evaluation.failed_count

    return PerformanceReport(
        measured_at=datetime.now(UTC),
        environment={
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "operating_system": platform.system(),
            "release": platform.release(),
            "database": "SQLite in-memory, isolated per case",
            "embedding_provider": "feature-hash-128",
            "reasoning_provider": "offline evaluation script where configured",
        },
        dataset_name=dataset.as_posix(),
        dataset_sha256=hashlib.sha256(dataset.read_bytes()).hexdigest(),
        warmup_runs=warmup_runs,
        measured_runs=measured_runs,
        cases_per_run=len(cases),
        evaluation_passed_count=passed,
        evaluation_failed_count=failed,
        metrics=summarize_trace_events(sink.events),
        measurement_notes=[
            "Durations use a monotonic high-resolution clock and are reported in milliseconds.",
            "p50 and p95 use the nearest-rank method over observed samples.",
            "Workflow latency excludes per-case database creation, seed loading, and policy ingestion.",
            "The reasoning provider is offline; external model latency and production concurrency are not measured.",
            "Token totals are null when a provider does not return token usage.",
            "Cost is null because no paid model call or model price was used in this measurement.",
        ],
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure ResolveOps workflow latency and component traces"
    )
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    report = measure_workflow_performance(
        arguments.dataset,
        warmup_runs=arguments.warmup_runs,
        measured_runs=arguments.runs,
    )
    rendered = json.dumps(report.model_dump(mode="json"), indent=2)
    if arguments.output is not None:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)
    if report.evaluation_failed_count:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
