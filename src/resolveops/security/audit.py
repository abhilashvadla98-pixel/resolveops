import logging
from typing import Protocol

from resolveops.security.models import SecurityEvent

LOGGER = logging.getLogger("resolveops.security")


class SecurityAuditSink(Protocol):
    def record(self, event: SecurityEvent) -> None: ...


class LoggingSecurityAuditSink:
    def record(self, event: SecurityEvent) -> None:
        LOGGER.info(
            "security_event type=%s subject=%s tenant=%s reason=%s",
            event.event_type.value,
            event.subject_id or "unknown",
            event.tenant_id or "unknown",
            event.reason_code,
        )


class InMemorySecurityAuditSink:
    def __init__(self) -> None:
        self.events: list[SecurityEvent] = []

    def record(self, event: SecurityEvent) -> None:
        self.events.append(event)
