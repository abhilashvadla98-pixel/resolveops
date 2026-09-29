from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256
from math import ceil, floor
from threading import Lock
from time import monotonic
from typing import Protocol

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from resolveops.observability.metrics import record_http_rejection


class Clock(Protocol):
    def __call__(self) -> float: ...


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_after_seconds: int
    retry_after_seconds: int | None = None


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class TokenBucketRateLimiter:
    def __init__(
        self,
        *,
        requests: int,
        period_seconds: int,
        max_buckets: int,
        idle_ttl_seconds: int,
        clock: Clock = monotonic,
    ) -> None:
        if requests < 1 or period_seconds < 1:
            raise ValueError("rate-limit requests and period must be positive")
        if max_buckets < 1:
            raise ValueError("rate-limit bucket count must be positive")
        if idle_ttl_seconds < period_seconds:
            raise ValueError("rate-limit idle TTL cannot be shorter than its period")
        self._capacity = requests
        self._refill_per_second = requests / period_seconds
        self._max_buckets = max_buckets
        self._idle_ttl_seconds = idle_ttl_seconds
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}
        self._lock = Lock()

    def consume(self, keys: Iterable[str]) -> RateLimitDecision:
        unique_keys = tuple(dict.fromkeys(keys))
        if not unique_keys:
            raise ValueError("at least one rate-limit key is required")
        now = self._clock()
        with self._lock:
            self._remove_idle_buckets(now)
            self._make_capacity(unique_keys)
            buckets = [self._refilled_bucket(key, now) for key in unique_keys]
            blocked = [bucket for bucket in buckets if bucket.tokens < 1]
            if blocked:
                retry_after = max(
                    ceil((1 - bucket.tokens) / self._refill_per_second) for bucket in blocked
                )
                return RateLimitDecision(
                    allowed=False,
                    limit=self._capacity,
                    remaining=0,
                    reset_after_seconds=self._reset_after(buckets),
                    retry_after_seconds=max(retry_after, 1),
                )
            for bucket in buckets:
                bucket.tokens -= 1
            return RateLimitDecision(
                allowed=True,
                limit=self._capacity,
                remaining=max(floor(min(bucket.tokens for bucket in buckets)), 0),
                reset_after_seconds=self._reset_after(buckets),
            )

    def _refilled_bucket(self, key: str, now: float) -> _Bucket:
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=float(self._capacity), updated_at=now)
            self._buckets[key] = bucket
            return bucket
        elapsed = max(now - bucket.updated_at, 0)
        bucket.tokens = min(
            float(self._capacity),
            bucket.tokens + elapsed * self._refill_per_second,
        )
        bucket.updated_at = now
        return bucket

    def _reset_after(self, buckets: list[_Bucket]) -> int:
        least_tokens = min(bucket.tokens for bucket in buckets)
        return max(ceil((self._capacity - least_tokens) / self._refill_per_second), 0)

    def _remove_idle_buckets(self, now: float) -> None:
        cutoff = now - self._idle_ttl_seconds
        expired = [key for key, bucket in self._buckets.items() if bucket.updated_at < cutoff]
        for key in expired:
            del self._buckets[key]

    def _make_capacity(self, incoming_keys: tuple[str, ...]) -> None:
        needed = sum(key not in self._buckets for key in incoming_keys)
        overflow = len(self._buckets) + needed - self._max_buckets
        if overflow <= 0:
            return
        protected = set(incoming_keys)
        oldest = sorted(
            (
                (bucket.updated_at, key)
                for key, bucket in self._buckets.items()
                if key not in protected
            )
        )
        for _, key in oldest[:overflow]:
            del self._buckets[key]


class TrafficProtectionMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int,
        rate_limiter: TokenBucketRateLimiter,
        exempt_paths: frozenset[str] = frozenset(),
    ) -> None:
        if max_body_bytes < 1:
            raise ValueError("maximum request body size must be positive")
        self._app = app
        self._max_body_bytes = max_body_bytes
        self._rate_limiter = rate_limiter
        self._exempt_paths = exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        path = str(scope.get("path", ""))
        decision: RateLimitDecision | None = None
        if path not in self._exempt_paths:
            decision = self._rate_limiter.consume(_rate_limit_keys(scope))
            if not decision.allowed:
                record_http_rejection("rate_limited")
                await _send_json(
                    scope,
                    receive,
                    send,
                    status_code=429,
                    detail="request rate limit exceeded",
                    headers=_rate_limit_headers(decision),
                )
                return

        headers = Headers(scope=scope)
        declared_length = headers.get("content-length")
        if declared_length is not None:
            try:
                parsed_length = int(declared_length)
            except ValueError:
                record_http_rejection("invalid_content_length")
                await _send_json(
                    scope,
                    receive,
                    send,
                    status_code=400,
                    detail="invalid Content-Length header",
                )
                return
            if parsed_length < 0:
                record_http_rejection("invalid_content_length")
                await _send_json(
                    scope,
                    receive,
                    send,
                    status_code=400,
                    detail="invalid Content-Length header",
                )
                return
            if parsed_length > self._max_body_bytes:
                record_http_rejection("request_body_too_large")
                await self._reject_large_body(scope, receive, send)
                return

        messages, too_large = await self._buffer_body(receive)
        if too_large:
            record_http_rejection("request_body_too_large")
            await self._reject_large_body(scope, receive, send)
            return
        iterator = iter(messages)

        async def replay_receive() -> Message:
            try:
                return next(iterator)
            except StopIteration:
                return await receive()

        async def add_rate_headers(message: Message) -> None:
            if decision is not None and message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                for name, value in _rate_limit_headers(decision).items():
                    response_headers.append(name, value)
            await send(message)

        await self._app(scope, replay_receive, add_rate_headers)

    async def _buffer_body(self, receive: Receive) -> tuple[list[Message], bool]:
        messages: list[Message] = []
        body_size = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                return messages, False
            body_size += len(message.get("body", b""))
            if body_size > self._max_body_bytes:
                return messages, True
            if not message.get("more_body", False):
                return messages, False

    async def _reject_large_body(self, scope: Scope, receive: Receive, send: Send) -> None:
        await _send_json(
            scope,
            receive,
            send,
            status_code=413,
            detail="request body exceeds configured limit",
        )


def _rate_limit_keys(scope: Scope) -> tuple[str, ...]:
    client = scope.get("client")
    network_identity = str(client[0]) if client else "unknown"
    keys = [_digest_key("network", network_identity)]
    authorization = Headers(scope=scope).get("authorization")
    if authorization:
        scheme, _, credential = authorization.partition(" ")
        if scheme.lower() == "bearer" and credential:
            keys.append(_digest_key("credential", credential))
    return tuple(keys)


def _digest_key(kind: str, value: str) -> str:
    return f"{kind}:{sha256(value.encode('utf-8')).hexdigest()}"


def _rate_limit_headers(decision: RateLimitDecision) -> dict[str, str]:
    headers = {
        "RateLimit-Limit": str(decision.limit),
        "RateLimit-Remaining": str(decision.remaining),
        "RateLimit-Reset": str(decision.reset_after_seconds),
    }
    if decision.retry_after_seconds is not None:
        headers["Retry-After"] = str(decision.retry_after_seconds)
    return headers


async def _send_json(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    status_code: int,
    detail: str,
    headers: dict[str, str] | None = None,
) -> None:
    response = JSONResponse(
        status_code=status_code,
        content={"detail": detail},
        headers=headers,
    )
    await response(scope, receive, send)
