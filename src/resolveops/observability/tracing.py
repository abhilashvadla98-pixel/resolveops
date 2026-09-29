import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from types import TracebackType
from typing import Self
from uuid import uuid4

from resolveops.observability.models import (
    TraceAttribute,
    TraceComponent,
    TraceEvent,
    TraceStatus,
)
from resolveops.observability.sinks import DEFAULT_TRACE_SINK, TraceSink

LOGGER = logging.getLogger("resolveops.observability")


@dataclass(frozen=True)
class TraceContext:
    trace_id: str
    sink: TraceSink
    workflow_id: str | None = None
    case_id: str | None = None


@dataclass
class Span:
    component: TraceComponent
    operation: str
    sink: TraceSink | None = None
    attributes: dict[str, TraceAttribute] = field(default_factory=dict)
    _trace_token: Token[TraceContext | None] | None = field(default=None, init=False)
    _span_token: Token[str | None] | None = field(default=None, init=False)
    _context: TraceContext | None = field(default=None, init=False)
    _span_id: str = field(default="", init=False)
    _parent_span_id: str | None = field(default=None, init=False)
    _started_at: datetime | None = field(default=None, init=False)
    _started_tick: float = field(default=0, init=False)
    _forced_error: bool = field(default=False, init=False)

    def __enter__(self) -> Self:
        context = _CURRENT_TRACE.get()
        if context is None:
            context = TraceContext(
                trace_id=uuid4().hex,
                sink=self.sink or DEFAULT_TRACE_SINK,
            )
            self._trace_token = _CURRENT_TRACE.set(context)
        self._context = context
        self._span_id = uuid4().hex[:16]
        self._parent_span_id = _CURRENT_SPAN.get()
        self._span_token = _CURRENT_SPAN.set(self._span_id)
        self._started_at = datetime.now(UTC)
        self._started_tick = perf_counter()
        return self

    def set_attribute(self, key: str, value: TraceAttribute) -> None:
        self.attributes[key] = value

    def mark_error(self, error_type: str) -> None:
        self._forced_error = True
        self.attributes["error_type"] = error_type

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        duration_ms = (perf_counter() - self._started_tick) * 1000
        if exception_type is not None:
            self.attributes["error_type"] = exception_type.__name__
        if self._context is None or self._started_at is None:
            raise RuntimeError("trace span exited before it started")
        event = TraceEvent(
            trace_id=self._context.trace_id,
            span_id=self._span_id,
            parent_span_id=self._parent_span_id,
            component=self.component,
            operation=self.operation,
            status=(
                TraceStatus.ERROR
                if exception_type is not None or self._forced_error
                else TraceStatus.OK
            ),
            started_at=self._started_at,
            duration_ms=duration_ms,
            workflow_id=self._context.workflow_id,
            case_id=self._context.case_id,
            attributes=self.attributes,
        )
        try:
            _safe_emit(self._context.sink, event)
        finally:
            if self._span_token is not None:
                _CURRENT_SPAN.reset(self._span_token)
            if self._trace_token is not None:
                _CURRENT_TRACE.reset(self._trace_token)


_CURRENT_TRACE: ContextVar[TraceContext | None] = ContextVar(
    "resolveops_trace_context", default=None
)
_CURRENT_SPAN: ContextVar[str | None] = ContextVar("resolveops_parent_span", default=None)


@contextmanager
def trace_context(
    sink: TraceSink,
    *,
    trace_id: str | None = None,
    workflow_id: str | None = None,
    case_id: str | None = None,
) -> Iterator[str]:
    parent = _CURRENT_TRACE.get()
    context = TraceContext(
        trace_id=trace_id or (parent.trace_id if parent else uuid4().hex),
        sink=sink,
        workflow_id=workflow_id or (parent.workflow_id if parent else None),
        case_id=case_id or (parent.case_id if parent else None),
    )
    token = _CURRENT_TRACE.set(context)
    try:
        yield context.trace_id
    finally:
        _CURRENT_TRACE.reset(token)


def observed_span(
    component: TraceComponent,
    operation: str,
    *,
    sink: TraceSink | None = None,
    attributes: dict[str, TraceAttribute] | None = None,
) -> Span:
    return Span(
        component=component,
        operation=operation,
        sink=sink,
        attributes=dict(attributes or {}),
    )


def record_trace_event(
    component: TraceComponent,
    operation: str,
    *,
    sink: TraceSink | None = None,
    status: TraceStatus = TraceStatus.OK,
    attributes: dict[str, TraceAttribute] | None = None,
) -> None:
    context = _CURRENT_TRACE.get()
    if context is None:
        context = TraceContext(trace_id=uuid4().hex, sink=sink or DEFAULT_TRACE_SINK)
    parent_span_id = _CURRENT_SPAN.get()
    resolved_attributes = dict(attributes or {})
    if status == TraceStatus.ERROR and "error_type" not in resolved_attributes:
        resolved_attributes["error_type"] = "recorded_error"
    _safe_emit(
        context.sink,
        TraceEvent(
            trace_id=context.trace_id,
            span_id=uuid4().hex[:16],
            parent_span_id=parent_span_id,
            component=component,
            operation=operation,
            status=status,
            started_at=datetime.now(UTC),
            duration_ms=0,
            workflow_id=context.workflow_id,
            case_id=context.case_id,
            attributes=resolved_attributes,
        ),
    )


def _safe_emit(sink: TraceSink, event: TraceEvent) -> None:
    try:
        sink.emit(event)
    except Exception:  # noqa: BLE001 - telemetry must not break business execution
        LOGGER.error(
            "trace_sink_failed component=%s operation=%s",
            event.component.value,
            event.operation,
        )
