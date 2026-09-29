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


DEFAULT_TRACE_SINK: TraceSink = LoggingTraceSink()
