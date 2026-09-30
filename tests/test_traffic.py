from collections.abc import Iterator

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from resolveops.security.traffic import (
    FailoverRateLimiter,
    RateLimitDecision,
    RedisTokenBucketRateLimiter,
    TokenBucketRateLimiter,
    TrafficProtectionMiddleware,
)


def limiter(
    *,
    requests: int = 100,
    period_seconds: int = 60,
) -> TokenBucketRateLimiter:
    return TokenBucketRateLimiter(
        requests=requests,
        period_seconds=period_seconds,
        max_buckets=100,
        idle_ttl_seconds=120,
    )


def protected_app(
    *,
    max_body_bytes: int = 16,
    requests: int = 100,
    exempt_paths: frozenset[str] = frozenset(),
) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        TrafficProtectionMiddleware,
        max_body_bytes=max_body_bytes,
        rate_limiter=limiter(requests=requests),
        exempt_paths=exempt_paths,
    )

    @app.get("/ok")
    def ok() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "alive"}

    @app.post("/echo")
    async def echo(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    return app


def test_token_bucket_checks_all_keys_without_partial_consumption() -> None:
    now = [0.0]
    rate_limiter = TokenBucketRateLimiter(
        requests=2,
        period_seconds=10,
        max_buckets=10,
        idle_ttl_seconds=20,
        clock=lambda: now[0],
    )
    keys = ("network:test", "credential:test")

    first = rate_limiter.consume(keys)
    second = rate_limiter.consume(keys)
    blocked = rate_limiter.consume(keys)

    assert first.allowed and first.remaining == 1
    assert second.allowed and second.remaining == 0
    assert not blocked.allowed
    assert blocked.retry_after_seconds == 5

    now[0] = 5.0
    refilled = rate_limiter.consume(keys)
    assert refilled.allowed
    assert refilled.remaining == 0


def test_request_body_limit_rejects_declared_and_streamed_oversize_bodies() -> None:
    with TestClient(protected_app(max_body_bytes=8)) as client:
        declared = client.post("/echo", content=b"123456789")

        def streamed_body() -> Iterator[bytes]:
            yield b"12345"
            yield b"67890"

        streamed = client.post("/echo", content=streamed_body())
        accepted = client.post("/echo", content=b"12345678")

    assert declared.status_code == 413
    assert declared.json() == {"detail": "request body exceeds configured limit"}
    assert streamed.status_code == 413
    assert accepted.status_code == 200
    assert accepted.json() == {"size": 8}


def test_rate_limit_returns_retry_metadata_without_echoing_credentials() -> None:
    token = "synthetic-secret-that-must-not-be-returned"
    with TestClient(protected_app(requests=2)) as client:
        first = client.get("/ok", headers={"Authorization": f"Bearer {token}"})
        second = client.get("/ok", headers={"Authorization": f"Bearer {token}"})
        blocked = client.get("/ok", headers={"Authorization": f"Bearer {token}"})

    assert first.status_code == second.status_code == 200
    assert first.headers["ratelimit-limit"] == "2"
    assert second.headers["ratelimit-remaining"] == "0"
    assert blocked.status_code == 429
    assert blocked.json() == {"detail": "request rate limit exceeded"}
    assert int(blocked.headers["retry-after"]) >= 1
    assert token not in blocked.text
    assert token not in repr(dict(blocked.headers))


def test_health_probe_is_exempt_from_rate_limit() -> None:
    app = protected_app(requests=1, exempt_paths=frozenset({"/health"}))
    with TestClient(app) as client:
        responses = [client.get("/health") for _ in range(3)]

    assert all(response.status_code == 200 for response in responses)
    assert all("ratelimit-limit" not in response.headers for response in responses)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"requests": 0, "period_seconds": 60, "max_buckets": 100, "idle_ttl_seconds": 120},
        {"requests": 1, "period_seconds": 60, "max_buckets": 0, "idle_ttl_seconds": 120},
        {"requests": 1, "period_seconds": 60, "max_buckets": 100, "idle_ttl_seconds": 59},
    ],
)
def test_invalid_rate_limit_configuration_fails_closed(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        TokenBucketRateLimiter(**kwargs)


class FakeRedisRateClient:
    def __init__(self, result: list[int] | None = None, *, unavailable: bool = False) -> None:
        self.result = result or [1, 4, 12, 0]
        self.unavailable = unavailable
        self.arguments: tuple[object, ...] = ()

    def eval(self, script: str, numkeys: int, *keys_and_args: object) -> list[int]:
        self.arguments = (script, numkeys, *keys_and_args)
        if self.unavailable:
            raise ConnectionError("synthetic Redis outage")
        return self.result


def test_distributed_limiter_uses_namespaced_hashed_keys() -> None:
    client = FakeRedisRateClient()
    shared = RedisTokenBucketRateLimiter(
        client,
        requests=5,
        period_seconds=60,
        idle_ttl_seconds=120,
    )

    decision = shared.consume(["network:already-hashed"])

    assert decision.allowed and decision.remaining == 4
    assert client.arguments[1] == 1
    assert client.arguments[2] == "resolveops:rate:network:already-hashed"


def test_distributed_limiter_falls_back_during_redis_outage() -> None:
    fallback_decision = RateLimitDecision(True, 3, 2, 1)

    class Fallback:
        def consume(self, keys: object) -> RateLimitDecision:
            return fallback_decision

    limiter = FailoverRateLimiter(
        RedisTokenBucketRateLimiter(
            FakeRedisRateClient(unavailable=True),
            requests=5,
            period_seconds=60,
            idle_ttl_seconds=120,
        ),
        Fallback(),
    )

    assert limiter.consume(["network:test"]) == fallback_decision
