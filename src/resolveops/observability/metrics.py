from collections import Counter, defaultdict
from collections.abc import Iterable
from math import ceil
from time import perf_counter

from prometheus_client import (
    CollectorRegistry,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client import (
    Counter as PrometheusCounter,
)

from resolveops.agents.models import AgentInvocationRecord
from resolveops.observability.models import (
    LatencyDistribution,
    ObservabilitySummary,
    OperationMetrics,
    TraceComponent,
    TraceEvent,
    TraceStatus,
)

METRICS_REGISTRY = CollectorRegistry(auto_describe=True)

HTTP_REQUESTS = PrometheusCounter(
    "resolveops_http_requests_total",
    "HTTP requests completed by the ResolveOps API.",
    ("method", "route", "status_code"),
    registry=METRICS_REGISTRY,
)
HTTP_REQUEST_DURATION = Histogram(
    "resolveops_http_request_duration_seconds",
    "ResolveOps API request duration in seconds.",
    ("method", "route"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
    registry=METRICS_REGISTRY,
)
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "resolveops_http_requests_in_progress",
    "ResolveOps API requests currently in progress.",
    ("method",),
    registry=METRICS_REGISTRY,
)
HTTP_REJECTIONS = PrometheusCounter(
    "resolveops_http_rejections_total",
    "HTTP requests rejected before business processing.",
    ("reason",),
    registry=METRICS_REGISTRY,
)
AGENT_RUNS = PrometheusCounter(
    "resolveops_agent_runs_total",
    "Multi-agent role invocations completed.",
    ("role", "status"),
    registry=METRICS_REGISTRY,
)
AGENT_RUN_DURATION = Histogram(
    "resolveops_agent_run_duration_seconds",
    "Multi-agent role invocation duration in seconds.",
    ("role",),
    registry=METRICS_REGISTRY,
)
AGENT_TOKENS = PrometheusCounter(
    "resolveops_agent_tokens_total",
    "Provider tokens recorded for multi-agent role invocations.",
    ("role", "direction"),
    registry=METRICS_REGISTRY,
)
AGENT_TOOL_CALLS = PrometheusCounter(
    "resolveops_agent_tool_calls_total",
    "Read-only agent tool calls completed.",
    ("tool", "status"),
    registry=METRICS_REGISTRY,
)
AGENT_QUEUE_JOBS = Gauge(
    "resolveops_agent_queue_jobs",
    "Durable agent jobs by active or dead-letter status.",
    ("status",),
    registry=METRICS_REGISTRY,
)


def start_http_request(method: str) -> float:
    HTTP_REQUESTS_IN_PROGRESS.labels(method=method).inc()
    return perf_counter()


def finish_http_request(
    *,
    method: str,
    route: str,
    status_code: int,
    started_tick: float,
) -> None:
    HTTP_REQUESTS_IN_PROGRESS.labels(method=method).dec()
    HTTP_REQUESTS.labels(
        method=method,
        route=route,
        status_code=str(status_code),
    ).inc()
    HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(
        max(perf_counter() - started_tick, 0)
    )


def record_http_rejection(reason: str) -> None:
    HTTP_REJECTIONS.labels(reason=reason).inc()


def record_agent_run(run: AgentInvocationRecord) -> None:
    role = run.role.value
    status = run.status.value
    AGENT_RUNS.labels(role=role, status=status).inc()
    latency_ms = run.latency_ms
    if isinstance(latency_ms, (int, float)):
        AGENT_RUN_DURATION.labels(role=role).observe(max(float(latency_ms) / 1_000, 0))
    for direction, attribute in (("input", "input_tokens"), ("output", "output_tokens")):
        value = run.input_tokens if attribute == "input_tokens" else run.output_tokens
        if isinstance(value, int):
            AGENT_TOKENS.labels(role=role, direction=direction).inc(value)


def record_agent_tool_call(tool_name: str, status: str) -> None:
    AGENT_TOOL_CALLS.labels(tool=tool_name, status=status).inc()


def record_agent_queue_health(
    *, pending: int, running: int, retrying: int, dead_letter: int
) -> None:
    for status, value in (
        ("pending", pending),
        ("running", running),
        ("retrying", retrying),
        ("dead_letter", dead_letter),
    ):
        AGENT_QUEUE_JOBS.labels(status=status).set(value)


def render_metrics() -> bytes:
    return generate_latest(METRICS_REGISTRY)


def summarize_trace_events(events: Iterable[TraceEvent]) -> ObservabilitySummary:
    collected = list(events)
    grouped: dict[tuple[TraceComponent, str], list[TraceEvent]] = defaultdict(list)
    for event in collected:
        grouped[(event.component, event.operation)].append(event)

    operations = [
        OperationMetrics(
            component=component,
            operation=operation,
            call_count=len(operation_events),
            failure_count=sum(event.status == TraceStatus.ERROR for event in operation_events),
            latency=_latency_distribution([event.duration_ms for event in operation_events]),
        )
        for (component, operation), operation_events in sorted(
            grouped.items(), key=lambda item: (item[0][0].value, item[0][1])
        )
    ]
    workflow_events = [
        event
        for event in collected
        if event.component == TraceComponent.WORKFLOW
        and isinstance(event.attributes.get("outcome"), str)
    ]
    workflow_outcomes = Counter(str(event.attributes["outcome"]) for event in workflow_events)
    retry_operations = {"execution_retry_scheduled", "verification_retry_scheduled"}
    input_tokens = _optional_integer_total(collected, "input_tokens")
    output_tokens = _optional_integer_total(collected, "output_tokens")
    cost = _optional_float_total(collected, "cost_usd")

    return ObservabilitySummary(
        trace_count=len({event.trace_id for event in collected}),
        event_count=len(collected),
        workflow_count=len(workflow_events),
        workflow_outcomes=dict(sorted(workflow_outcomes.items())),
        operations=operations,
        retry_scheduled_count=sum(event.operation in retry_operations for event in collected),
        total_input_tokens=input_tokens,
        total_output_tokens=output_tokens,
        total_cost_usd=cost,
    )


def _latency_distribution(samples: list[float]) -> LatencyDistribution:
    ordered = sorted(samples)
    return LatencyDistribution(
        sample_count=len(ordered),
        minimum_ms=ordered[0],
        p50_ms=_nearest_rank(ordered, 0.50),
        p95_ms=_nearest_rank(ordered, 0.95),
        maximum_ms=ordered[-1],
    )


def _nearest_rank(ordered: list[float], percentile: float) -> float:
    return ordered[max(ceil(percentile * len(ordered)) - 1, 0)]


def _optional_integer_total(events: list[TraceEvent], attribute: str) -> int | None:
    values = [event.attributes.get(attribute) for event in events]
    integers = [value for value in values if isinstance(value, int) and not isinstance(value, bool)]
    return sum(integers) if integers else None


def _optional_float_total(events: list[TraceEvent], attribute: str) -> float | None:
    values = [event.attributes.get(attribute) for event in events]
    numbers = [
        float(value)
        for value in values
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    ]
    return sum(numbers) if numbers else None
