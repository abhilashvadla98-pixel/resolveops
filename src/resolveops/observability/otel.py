from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from resolveops.observability.models import TraceEvent, TraceStatus
from resolveops.observability.sinks import CompositeTraceSink, LoggingTraceSink, TraceSink

LOGGER = logging.getLogger("resolveops.observability")


class OpenTelemetryTraceSink:
    """Map completed ResolveOps trace events to standard OpenTelemetry spans."""

    def __init__(self, tracer: Any, *, provider: Any | None = None) -> None:
        self._tracer = tracer
        self._provider = provider

    @classmethod
    def from_endpoint(cls, endpoint: str, *, service_name: str) -> OpenTelemetryTraceSink:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        return cls(provider.get_tracer("resolveops"), provider=provider)

    def emit(self, event: TraceEvent) -> None:
        start_ns = int(event.started_at.timestamp() * 1_000_000_000)
        end_ns = int(
            (event.started_at + timedelta(milliseconds=event.duration_ms)).timestamp()
            * 1_000_000_000
        )
        span = self._tracer.start_span(
            f"{event.component.value}.{event.operation}",
            start_time=start_ns,
        )
        attributes: dict[str, str | int | float | bool] = {
            "resolveops.trace_id": event.trace_id,
            "resolveops.span_id": event.span_id,
            "resolveops.component": event.component.value,
            "resolveops.status": event.status.value,
        }
        if event.parent_span_id is not None:
            attributes["resolveops.parent_span_id"] = event.parent_span_id
        if event.workflow_id is not None:
            attributes["resolveops.workflow_id"] = event.workflow_id
        if event.case_id is not None:
            attributes["resolveops.case_id"] = event.case_id
        attributes.update(
            {
                f"resolveops.{key}": value
                for key, value in event.attributes.items()
                if value is not None
            }
        )
        span.set_attributes(attributes)
        if event.status == TraceStatus.ERROR:
            from opentelemetry.trace import Status, StatusCode

            span.set_status(Status(StatusCode.ERROR))
        span.end(end_time=end_ns)

    def shutdown(self) -> None:
        if self._provider is not None:
            self._provider.shutdown()


def build_configured_trace_sink(
    endpoint: str | None,
    *,
    service_name: str,
) -> TraceSink:
    logging_sink = LoggingTraceSink()
    if endpoint is None:
        return logging_sink
    try:
        return CompositeTraceSink(
            [
                logging_sink,
                OpenTelemetryTraceSink.from_endpoint(endpoint, service_name=service_name),
            ]
        )
    except Exception:
        LOGGER.exception("OTLP exporter could not start; continuing with local structured traces")
        return logging_sink
