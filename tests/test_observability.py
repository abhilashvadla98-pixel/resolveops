from pathlib import Path

import pytest

from resolveops.evaluation.dataset import load_workflow_evaluation_cases
from resolveops.evaluation.workflow import evaluate_workflow_cases
from resolveops.observability.benchmark import measure_workflow_performance
from resolveops.observability.metrics import (
    record_agent_queue_health,
    record_agent_tool_call,
    render_metrics,
    summarize_trace_events,
)
from resolveops.observability.models import TraceComponent, TraceEvent, TraceStatus
from resolveops.observability.sinks import InMemoryTraceSink
from resolveops.observability.tracing import observed_span, trace_context

DATASET = Path("evals/workflows/customer_operations.jsonl")


class FailingTraceSink:
    def emit(self, event: TraceEvent) -> None:
        raise RuntimeError("telemetry backend unavailable")


def test_nested_trace_spans_preserve_context_and_never_log_exception_messages() -> None:
    sink = InMemoryTraceSink()

    with (
        trace_context(
            sink,
            trace_id="a" * 32,
            workflow_id="WORKFLOW-OBS-1",
            case_id="CASE-1001",
        ),
        observed_span(TraceComponent.WORKFLOW, "run") as root,
    ):
        root.set_attribute("outcome", "needs_review")
        with (
            pytest.raises(RuntimeError, match="sensitive failure text"),
            observed_span(TraceComponent.TOOL, "issue_refund"),
        ):
            raise RuntimeError("sensitive failure text")

    assert len(sink.events) == 2
    tool, workflow = sink.events
    assert tool.trace_id == workflow.trace_id == "a" * 32
    assert tool.parent_span_id == workflow.span_id
    assert tool.workflow_id == "WORKFLOW-OBS-1"
    assert tool.case_id == "CASE-1001"
    assert tool.status == TraceStatus.ERROR
    assert tool.attributes["error_type"] == "RuntimeError"
    assert "sensitive failure text" not in repr(sink.events)


def test_telemetry_sink_failure_does_not_break_business_execution() -> None:
    with observed_span(
        TraceComponent.TOOL,
        "create_ticket",
        sink=FailingTraceSink(),
    ):
        business_result = "completed"

    assert business_result == "completed"


def test_workflow_trace_covers_nodes_retrieval_tools_and_llm() -> None:
    cases = load_workflow_evaluation_cases(DATASET)
    selected = [cases[1], cases[2]]
    sink = InMemoryTraceSink()

    report = evaluate_workflow_cases(
        selected,
        dataset_name="observability-integration",
        observability_sink=sink,
    )
    summary = summarize_trace_events(sink.events)

    assert report.passed_count == 2
    assert summary.trace_count == 2
    assert summary.workflow_count == 2
    assert summary.workflow_outcomes == {"action_verified": 2}
    assert summary.total_input_tokens is None
    assert summary.total_output_tokens is None
    assert summary.total_cost_usd is None
    components = {event.component for event in sink.events}
    assert components >= {
        TraceComponent.WORKFLOW,
        TraceComponent.WORKFLOW_NODE,
        TraceComponent.RETRIEVAL,
        TraceComponent.TOOL,
        TraceComponent.LLM,
    }
    for event in sink.events:
        assert event.duration_ms >= 0
        assert event.workflow_id is not None
        assert event.case_id == "CASE-1001"


def test_failed_tool_and_retry_are_measured() -> None:
    cases = load_workflow_evaluation_cases(DATASET)
    timeout_case = next(case for case in cases if case.evaluation_id == "WF-EVAL-020")
    sink = InMemoryTraceSink()

    report = evaluate_workflow_cases(
        [timeout_case],
        dataset_name="retry-observability",
        observability_sink=sink,
    )
    summary = summarize_trace_events(sink.events)

    assert report.passed_count == 1
    assert summary.retry_scheduled_count == 1
    refund_metrics = next(
        metric
        for metric in summary.operations
        if metric.component == TraceComponent.TOOL and metric.operation == "issue_refund"
    )
    assert refund_metrics.call_count == 1
    assert refund_metrics.failure_count == 1


def test_provider_and_grounding_failures_are_both_llm_failures() -> None:
    cases = load_workflow_evaluation_cases(DATASET)
    failure_ids = {"WF-EVAL-013", "WF-EVAL-014"}
    sink = InMemoryTraceSink()

    report = evaluate_workflow_cases(
        [case for case in cases if case.evaluation_id in failure_ids],
        dataset_name="llm-failure-observability",
        observability_sink=sink,
    )
    summary = summarize_trace_events(sink.events)
    llm_metrics = next(
        metric for metric in summary.operations if metric.component == TraceComponent.LLM
    )

    assert report.passed_count == 2
    assert llm_metrics.call_count == 2
    assert llm_metrics.failure_count == 2


def test_performance_report_uses_real_trace_samples() -> None:
    report = measure_workflow_performance(DATASET, warmup_runs=0, measured_runs=1)

    assert report.cases_per_run == 24
    assert report.evaluation_passed_count == 24
    assert report.evaluation_failed_count == 0
    assert report.metrics.workflow_count == 24
    workflow_metrics = next(
        metric
        for metric in report.metrics.operations
        if metric.component == TraceComponent.WORKFLOW and metric.operation == "run"
    )
    assert workflow_metrics.latency.sample_count == 24
    assert workflow_metrics.latency.minimum_ms <= workflow_metrics.latency.p50_ms
    assert workflow_metrics.latency.p50_ms <= workflow_metrics.latency.p95_ms
    assert workflow_metrics.latency.p95_ms <= workflow_metrics.latency.maximum_ms


def test_agent_tool_and_queue_prometheus_metrics_are_exposed() -> None:
    record_agent_tool_call("get_case", "completed")
    record_agent_queue_health(pending=2, running=1, retrying=0, dead_letter=1)

    payload = render_metrics().decode("utf-8")

    assert "resolveops_agent_tool_calls_total" in payload
    assert 'tool="get_case"' in payload
    assert 'resolveops_agent_queue_jobs{status="pending"} 2.0' in payload
