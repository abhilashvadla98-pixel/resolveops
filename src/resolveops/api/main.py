from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.responses import JSONResponse

from resolveops.api.console import router as console_router
from resolveops.api.demo import router as demo_router
from resolveops.api.dependencies import get_tenant_registry
from resolveops.api.employee_it import router as employee_it_router
from resolveops.api.events import router as events_router
from resolveops.api.metrics import router as metrics_router
from resolveops.api.operations import router as operations_router
from resolveops.api.simulator import router as simulator_router
from resolveops.config import get_traffic_protection_settings
from resolveops.database.health import DatabaseReadinessError, verify_database_readiness
from resolveops.observability.metrics import finish_http_request, start_http_request
from resolveops.observability.models import TraceComponent
from resolveops.observability.sinks import DEFAULT_TRACE_SINK
from resolveops.observability.tracing import observed_span, trace_context
from resolveops.security.tenancy import TenantSessionRegistry
from resolveops.security.traffic import TokenBucketRateLimiter, TrafficProtectionMiddleware

app = FastAPI(
    title="ResolveOps API",
    description=(
        "APIs for ResolveOps and its simulated Customer Operations and Employee/IT systems."
    ),
)
app.include_router(simulator_router)
app.include_router(demo_router)
app.include_router(employee_it_router)
app.include_router(events_router)
app.include_router(metrics_router)
app.include_router(operations_router)
app.include_router(console_router)

traffic_settings = get_traffic_protection_settings()
app.add_middleware(
    TrafficProtectionMiddleware,
    max_body_bytes=traffic_settings.max_request_body_bytes,
    rate_limiter=TokenBucketRateLimiter(
        requests=traffic_settings.rate_limit_requests,
        period_seconds=traffic_settings.rate_limit_period_seconds,
        max_buckets=traffic_settings.rate_limit_max_buckets,
        idle_ttl_seconds=traffic_settings.rate_limit_idle_ttl_seconds,
    ),
    exempt_paths=frozenset({"/health", "/health/live", "/health/ready"}),
)


@app.middleware("http")
async def observe_http_request(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    method = request.method
    started_tick = start_http_request(method)
    response: Response | None = None
    response_status = status.HTTP_500_INTERNAL_SERVER_ERROR
    with (
        trace_context(DEFAULT_TRACE_SINK) as trace_id,
        observed_span(
            TraceComponent.API,
            "http_request",
            attributes={"method": method},
        ) as span,
    ):
        try:
            response = await call_next(request)
            response_status = response.status_code
            response.headers["X-ResolveOps-Trace-ID"] = trace_id
            return response
        finally:
            route = request.scope.get("route")
            route_template = getattr(route, "path", "unmatched")
            span.set_attribute("route", route_template)
            span.set_attribute("status_code", response_status)
            if response_status >= 500:
                span.mark_error("http_server_error")
            finish_http_request(
                method=method,
                route=route_template,
                status_code=response_status,
                started_tick=started_tick,
            )


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/live")
def liveness_check() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready", response_model=None)
def readiness_check(
    registry: Annotated[TenantSessionRegistry, Depends(get_tenant_registry)],
) -> dict[str, str] | JSONResponse:
    try:
        verify_database_readiness(registry)
    except DatabaseReadinessError:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "not_ready"},
        )
    return {"status": "ready"}
