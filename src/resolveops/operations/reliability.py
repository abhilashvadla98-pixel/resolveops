from collections.abc import Callable
from dataclasses import dataclass
from time import sleep


@dataclass(frozen=True)
class ReliabilityPolicy:
    max_attempts: int = 3
    initial_backoff_seconds: float = 0.05
    backoff_multiplier: float = 2.0
    max_backoff_seconds: float = 0.5
    attempt_timeout_seconds: float = 10.0
    lease_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds cannot be negative")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be at least 1")
        if self.max_backoff_seconds < 0:
            raise ValueError("max_backoff_seconds cannot be negative")
        if self.attempt_timeout_seconds <= 0:
            raise ValueError("attempt_timeout_seconds must be positive")
        if self.lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if self.lease_seconds < self.attempt_timeout_seconds:
            raise ValueError("lease_seconds must cover the full attempt timeout")

    def backoff_seconds(self, completed_attempt: int) -> float:
        if completed_attempt < 1:
            raise ValueError("completed_attempt must be at least 1")
        delay = self.initial_backoff_seconds * (self.backoff_multiplier ** (completed_attempt - 1))
        return min(delay, self.max_backoff_seconds)


Sleeper = Callable[[float], None]
DEFAULT_SLEEPER: Sleeper = sleep
