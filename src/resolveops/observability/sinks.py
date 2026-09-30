import json
import logging
from typing import Protocol

from resolveops.observability.models import TraceEvent

LOGGER = logging.getLogger("resolveops.observability")


class TraceSink(Protocol):
    def emit(self, event: TraceEvent) -> None: ...


class LoggingTraceSink:
    """Emit one machine-readable JSON object per completed span."""

    def emit(self, event: TraceEvent) -> None:
        LOGGER.info(
            "resolveops_trace %s",
            json.dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
        )


class InMemoryTraceSink:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def emit(self, event: TraceEvent) -> None:
        self.events.append(event)


class CompositeTraceSink:
    def __init__(self, sinks: list[TraceSink]) -> None:
        if not sinks:
            raise ValueError("composite trace sink requires at least one sink")
        self.sinks = list(sinks)

    def emit(self, event: TraceEvent) -> None:
        for sink in self.sinks:
            try:
                sink.emit(event)
            except Exception:  # noqa: BLE001 - one exporter cannot block the others
                LOGGER.error("trace_export_failed exporter=%s", type(sink).__name__)


class ConfigurableTraceSink:
    def __init__(self, sink: TraceSink) -> None:
        self._sink = sink

    def configure(self, sink: TraceSink) -> None:
        self._sink = sink

    def emit(self, event: TraceEvent) -> None:
        self._sink.emit(event)


DEFAULT_TRACE_SINK = ConfigurableTraceSink(LoggingTraceSink())


def configure_default_trace_sink(sink: TraceSink) -> None:
    DEFAULT_TRACE_SINK.configure(sink)
