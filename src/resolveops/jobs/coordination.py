from __future__ import annotations

from importlib import import_module
from typing import Protocol, cast


class WakeupChannel(Protocol):
    def notify(self) -> None: ...

    def wait(self, timeout_seconds: int) -> None: ...


class PollingWakeupChannel:
    def notify(self) -> None:
        return None

    def wait(self, timeout_seconds: int) -> None:
        from time import sleep

        sleep(timeout_seconds)


class _RedisClient(Protocol):
    def lpush(self, name: str, *values: str) -> object: ...

    def ltrim(self, name: str, start: int, end: int) -> object: ...

    def blpop(self, keys: list[str], timeout: int) -> object: ...


class RedisWakeupChannel:
    """Redis contains only a wake-up marker; durable job data stays in PostgreSQL."""

    def __init__(self, client: _RedisClient, *, namespace: str = "resolveops") -> None:
        self._client = client
        self._key = f"{namespace}:agent-jobs:wakeup"

    @classmethod
    def from_url(cls, redis_url: str, *, namespace: str = "resolveops") -> RedisWakeupChannel:
        redis_module = import_module("redis")
        client = cast(_RedisClient, redis_module.Redis.from_url(redis_url, decode_responses=True))
        return cls(client, namespace=namespace)

    def notify(self) -> None:
        self._client.lpush(self._key, "1")
        self._client.ltrim(self._key, 0, 99)

    def wait(self, timeout_seconds: int) -> None:
        self._client.blpop([self._key], timeout=timeout_seconds)


def build_wakeup_channel(redis_url: str | None) -> WakeupChannel:
    if not redis_url:
        return PollingWakeupChannel()
    return RedisWakeupChannel.from_url(redis_url)
