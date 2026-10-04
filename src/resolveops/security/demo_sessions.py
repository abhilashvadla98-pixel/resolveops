import base64
import hashlib
import hmac
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from resolveops.models.common import AwareDatetime, DomainModel, Identifier
from resolveops.operations.models import ActorRole
from resolveops.security.models import SecurityPrincipal


class DemoSessionError(ValueError):
    pass


class DemoSession(DomainModel):
    access_token: str
    expires_at: AwareDatetime
    workspace_label: str = "Demo workspace · synthetic data"
    isolated_workspace: bool = False
    data_mode: Literal["synthetic", "unknown"] = "unknown"
    execution_mode: Literal["rules_only", "live_model_enabled", "unknown"] = "unknown"


class DemoTokenClaims(DomainModel):
    session_id: Identifier
    tenant_id: Identifier
    expires_at: int


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class DemoSessionAuthenticator:
    def __init__(
        self,
        secret: str,
        *,
        tenant_id: str,
        ttl_seconds: int = 1800,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if len(secret) < 32:
            raise ValueError("demo session secret must contain at least 32 characters")
        self.secret = secret.encode("utf-8")
        self.tenant_id = tenant_id
        self.ttl_seconds = ttl_seconds
        self.clock = clock or (lambda: datetime.now(UTC))

    def create(self) -> DemoSession:
        expires_at = self.clock() + timedelta(seconds=self.ttl_seconds)
        claims = DemoTokenClaims(
            session_id=f"DEMO-{uuid4().hex[:20].upper()}",
            tenant_id=self.tenant_id,
            expires_at=int(expires_at.timestamp()),
        )
        payload = _encode(claims.model_dump_json().encode("utf-8"))
        signature = _encode(hmac.new(self.secret, payload.encode("ascii"), hashlib.sha256).digest())
        return DemoSession(access_token=f"demo.{payload}.{signature}", expires_at=expires_at)

    def authenticate(self, token: str) -> SecurityPrincipal:
        try:
            prefix, payload, presented_signature = token.split(".", maxsplit=2)
            expected_signature = _encode(
                hmac.new(self.secret, payload.encode("ascii"), hashlib.sha256).digest()
            )
            if prefix != "demo" or not hmac.compare_digest(presented_signature, expected_signature):
                raise DemoSessionError("invalid demo session")
            claims = TypeAdapter(DemoTokenClaims).validate_json(_decode(payload))
        except (ValueError, UnicodeDecodeError, ValidationError) as exc:
            raise DemoSessionError("invalid demo session") from exc
        if claims.tenant_id != self.tenant_id:
            raise DemoSessionError("invalid demo tenant")
        if int(self.clock().timestamp()) >= claims.expires_at:
            raise DemoSessionError("demo session expired")
        return SecurityPrincipal(
            subject_id=claims.session_id,
            tenant_id=self.tenant_id,
            role=ActorRole.APPROVER,
            authentication_method="demo_session",
        )
