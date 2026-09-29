import json
from collections.abc import Mapping
from datetime import UTC, datetime

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import Engine, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker

from resolveops.database.session import create_database_engine, create_session_factory
from resolveops.models.common import Identifier
from resolveops.security.audit import LoggingSecurityAuditSink, SecurityAuditSink
from resolveops.security.models import SecurityEvent, SecurityEventType, SecurityPrincipal


class TenantAccessError(Exception):
    pass


class TenantConfigurationError(ValueError):
    pass


class TenantSessionRegistry:
    """Select a physically isolated database using only the authenticated principal."""

    def __init__(
        self,
        session_factories: Mapping[str, sessionmaker[Session]],
        *,
        engines: tuple[Engine, ...] = (),
        audit_sink: SecurityAuditSink | None = None,
    ) -> None:
        if not session_factories:
            raise TenantConfigurationError("at least one tenant database is required")
        factories = list(session_factories.values())
        if len(factories) != len({id(factory) for factory in factories}):
            raise TenantConfigurationError(
                "each tenant must use a separate database session factory"
            )
        adapter = TypeAdapter(Identifier)
        try:
            tenant_ids = [adapter.validate_python(item) for item in session_factories]
        except ValidationError as exc:
            raise TenantConfigurationError("tenant database ID is invalid") from exc
        if len(tenant_ids) != len(set(tenant_ids)):
            raise TenantConfigurationError("tenant database IDs must be unique")
        self._session_factories = dict(session_factories)
        self._engines = engines
        self.audit_sink = audit_sink or LoggingSecurityAuditSink()

    @classmethod
    def from_database_urls_json(
        cls, raw_json: str, *, audit_sink: SecurityAuditSink | None = None
    ) -> "TenantSessionRegistry":
        try:
            payload = json.loads(raw_json)
            database_urls = TypeAdapter(dict[str, str]).validate_python(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise TenantConfigurationError("tenant database configuration is invalid") from exc
        database_targets = [
            _database_target(database_url) for database_url in database_urls.values()
        ]
        if len(database_targets) != len(set(database_targets)):
            raise TenantConfigurationError("each tenant must use a separate database target")
        engines = tuple(create_database_engine(url) for url in database_urls.values())
        factories = {
            tenant_id: create_session_factory(engine)
            for tenant_id, engine in zip(database_urls, engines, strict=True)
        }
        return cls(factories, engines=engines, audit_sink=audit_sink)

    def session_factory(self, principal: SecurityPrincipal) -> sessionmaker[Session]:
        factory = self._session_factories.get(principal.tenant_id)
        if factory is None:
            self.audit_sink.record(
                SecurityEvent(
                    event_type=SecurityEventType.TENANT_ACCESS_DENIED,
                    occurred_at=datetime.now(UTC),
                    subject_id=principal.subject_id,
                    tenant_id=principal.tenant_id,
                    reason_code="tenant_database_unavailable",
                )
            )
            raise TenantAccessError("tenant access denied")
        return factory

    def session_factories(self) -> tuple[sessionmaker[Session], ...]:
        """Return configured factories for internal health checks without exposing tenant IDs."""
        return tuple(self._session_factories.values())

    def close(self) -> None:
        for engine in self._engines:
            engine.dispose()


def _database_target(database_url: str) -> tuple[str, str | None, int | None, str | None]:
    try:
        parsed = make_url(database_url)
    except ArgumentError as exc:
        raise TenantConfigurationError("tenant database URL is invalid") from exc
    backend = parsed.get_backend_name()
    port = parsed.port or {"postgresql": 5432}.get(backend)
    return (backend, parsed.host, port, parsed.database)
