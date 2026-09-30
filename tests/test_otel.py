from datetime import UTC, datetime

from resolveops.observability.models import TraceComponent, TraceEvent, TraceStatus
from resolveops.observability.otel import OpenTelemetryTraceSink, build_configured_trace_sink
from resolveops.observability.sinks import LoggingTraceSink


class FakeSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}
        self.status: object | None = None
        self.end_time: int | None = None

    def set_attributes(self, attributes: dict[str, object]) -> None:
        self.attributes = attributes

    def set_status(self, status: object) -> None:
        self.status = status

    def end(self, *, end_time: int) -> None:
        self.end_time = end_time


class FakeTracer:
    def __init__(self) -> None:
        self.name: str | None = None
        self.start_time: int | None = None
        self.span = FakeSpan()

    def start_span(self, name: str, *, start_time: int) -> FakeSpan:
        self.name = name
        self.start_time = start_time
        return self.span


def test_otel_sink_maps_safe_completed_event_fields() -> None:
    tracer = FakeTracer()
    sink = OpenTelemetryTraceSink(tracer)
    event = TraceEvent(
        trace_id="a" * 32,
        span_id="b" * 16,
        parent_span_id="c" * 16,
        component=TraceComponent.LLM,
        operation="agent_policy",
        status=TraceStatus.OK,
        started_at=datetime(2026, 9, 29, 12, tzinfo=UTC),
        duration_ms=12.5,
        workflow_id="WF-1",
        case_id="CASE-1",
        attributes={"agent_role": "policy", "input_tokens": 200},
    )

    sink.emit(event)

    assert tracer.name == "llm.agent_policy"
    assert tracer.span.attributes["resolveops.trace_id"] == "a" * 32
    assert tracer.span.attributes["resolveops.agent_role"] == "policy"
    assert tracer.span.attributes["resolveops.input_tokens"] == 200
    assert tracer.span.end_time is not None
    assert tracer.span.end_time > (tracer.start_time or 0)


def test_no_otlp_endpoint_keeps_local_logging_sink() -> None:
    assert isinstance(
        build_configured_trace_sink(None, service_name="resolveops-test"), LoggingTraceSink
    )
