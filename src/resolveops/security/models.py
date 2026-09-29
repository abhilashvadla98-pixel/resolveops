from enum import Enum

from pydantic import Field

from resolveops.models.common import AwareDatetime, DomainModel, Identifier, NonEmptyText
from resolveops.operations.models import Actor, ActorRole


class SecurityPrincipal(DomainModel):
    subject_id: Identifier
    tenant_id: Identifier
    role: ActorRole
    authentication_method: str = "api_key"

    def actor(self) -> Actor:
        return Actor(actor_id=self.subject_id, role=self.role)


class APIKeyIdentity(DomainModel):
    key_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    subject_id: Identifier
    tenant_id: Identifier
    role: ActorRole
    enabled: bool = True

    def principal(self) -> SecurityPrincipal:
        return SecurityPrincipal(
            subject_id=self.subject_id,
            tenant_id=self.tenant_id,
            role=self.role,
        )


class SecurityEventType(str, Enum):
    AUTHENTICATION_SUCCEEDED = "authentication_succeeded"
    AUTHENTICATION_FAILED = "authentication_failed"
    TENANT_ACCESS_DENIED = "tenant_access_denied"


class SecurityEvent(DomainModel):
    event_type: SecurityEventType
    occurred_at: AwareDatetime
    subject_id: Identifier | None = None
    tenant_id: Identifier | None = None
    reason_code: NonEmptyText
