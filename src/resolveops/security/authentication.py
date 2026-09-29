import hashlib
import hmac
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from pydantic import TypeAdapter, ValidationError

from resolveops.security.audit import LoggingSecurityAuditSink, SecurityAuditSink
from resolveops.security.models import (
    APIKeyIdentity,
    SecurityEvent,
    SecurityEventType,
    SecurityPrincipal,
)


class AuthenticationError(Exception):
    pass


class AuthenticationConfigurationError(ValueError):
    pass


def hash_api_key(api_key: str) -> str:
    if len(api_key) < 32:
        raise ValueError("API keys must contain at least 32 characters")
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


class APIKeyAuthenticator:
    def __init__(
        self,
        identities: Sequence[APIKeyIdentity],
        *,
        audit_sink: SecurityAuditSink | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not identities:
            raise AuthenticationConfigurationError(
                "at least one API key identity must be configured"
            )
        digests = [identity.key_sha256 for identity in identities]
        if len(digests) != len(set(digests)):
            raise AuthenticationConfigurationError("API key digests must be unique")
        self.identities = tuple(identities)
        self.audit_sink = audit_sink or LoggingSecurityAuditSink()
        self.clock = clock or (lambda: datetime.now(UTC))

    @classmethod
    def from_json(cls, raw_json: str) -> "APIKeyAuthenticator":
        try:
            payload = json.loads(raw_json)
            identities = TypeAdapter(list[APIKeyIdentity]).validate_python(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise AuthenticationConfigurationError(
                "API key identity configuration is invalid"
            ) from exc
        return cls(identities)

    def authenticate(self, api_key: str) -> SecurityPrincipal:
        try:
            presented_digest = hash_api_key(api_key)
        except ValueError:
            self.record_failure("invalid_credential")
            raise AuthenticationError("authentication failed") from None

        match: APIKeyIdentity | None = None
        for identity in self.identities:
            if hmac.compare_digest(presented_digest, identity.key_sha256):
                match = identity
        if match is None or not match.enabled:
            self.record_failure("invalid_credential")
            raise AuthenticationError("authentication failed")

        principal = match.principal()
        self.audit_sink.record(
            SecurityEvent(
                event_type=SecurityEventType.AUTHENTICATION_SUCCEEDED,
                occurred_at=self.clock(),
                subject_id=principal.subject_id,
                tenant_id=principal.tenant_id,
                reason_code="valid_api_key",
            )
        )
        return principal

    def record_failure(self, reason_code: str) -> None:
        """Record a safe authentication failure without storing credential material."""
        self.audit_sink.record(
            SecurityEvent(
                event_type=SecurityEventType.AUTHENTICATION_FAILED,
                occurred_at=self.clock(),
                reason_code=reason_code,
            )
        )
