import hashlib
import json
from collections.abc import Callable
from datetime import datetime

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from resolveops.events.webhook import WebhookVerifier
from resolveops.operations.models import ActorRole
from resolveops.security.models import SecurityPrincipal
from resolveops.security.tenancy import TenantAccessError, TenantSessionRegistry


class WebhookTenantError(Exception):
    pass


class WebhookTenantConfigurationError(ValueError):
    pass


class TenantWebhookRegistry:
    def __init__(
        self,
        tenant_secrets: dict[str, str],
        tenant_sessions: TenantSessionRegistry,
        *,
        tolerance_seconds: int = 300,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not tenant_secrets:
            raise WebhookTenantConfigurationError("at least one tenant webhook secret is required")
        fingerprints = [
            hashlib.sha256(secret.encode("utf-8")).hexdigest() for secret in tenant_secrets.values()
        ]
        if len(fingerprints) != len(set(fingerprints)):
            raise WebhookTenantConfigurationError("webhook secrets must be unique per tenant")
        try:
            self._verifiers = {
                tenant_id: WebhookVerifier(
                    secret,
                    tolerance_seconds=tolerance_seconds,
                    clock=clock,
                )
                for tenant_id, secret in tenant_secrets.items()
            }
        except ValueError as exc:
            raise WebhookTenantConfigurationError(
                "tenant webhook configuration is invalid"
            ) from exc
        self.tenant_sessions = tenant_sessions

    @classmethod
    def from_json(
        cls,
        raw_json: str,
        tenant_sessions: TenantSessionRegistry,
        *,
        tolerance_seconds: int = 300,
        clock: Callable[[], datetime] | None = None,
    ) -> "TenantWebhookRegistry":
        try:
            payload = json.loads(raw_json)
            secrets = TypeAdapter(dict[str, str]).validate_python(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise WebhookTenantConfigurationError(
                "tenant webhook configuration is invalid"
            ) from exc
        return cls(
            secrets,
            tenant_sessions,
            tolerance_seconds=tolerance_seconds,
            clock=clock,
        )

    def context(self, tenant_id: str | None) -> tuple[WebhookVerifier, sessionmaker[Session]]:
        resolved_tenant_id = tenant_id or ""
        verifier = self._verifiers.get(resolved_tenant_id)
        if verifier is None:
            raise WebhookTenantError("webhook authentication failed")
        principal = SecurityPrincipal(
            subject_id="REFUND-WEBHOOK",
            tenant_id=resolved_tenant_id,
            role=ActorRole.SYSTEM,
        )
        try:
            factory = self.tenant_sessions.session_factory(principal)
        except TenantAccessError as exc:
            raise WebhookTenantError("webhook authentication failed") from exc
        return verifier, factory
