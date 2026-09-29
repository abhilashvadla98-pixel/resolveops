from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from resolveops.config import get_settings
from resolveops.database.session import create_database_engine, create_session_factory
from resolveops.events.webhook import WebhookVerifier
from resolveops.security.authentication import (
    APIKeyAuthenticator,
    AuthenticationConfigurationError,
    AuthenticationError,
)
from resolveops.security.models import SecurityPrincipal
from resolveops.security.tenancy import (
    TenantAccessError,
    TenantSessionRegistry,
)
from resolveops.security.webhooks import (
    TenantWebhookRegistry,
    WebhookTenantConfigurationError,
)

bearer_scheme = HTTPBearer(auto_error=False)


@lru_cache
def get_engine() -> Engine:
    return create_database_engine(get_settings().resolved_database_url())


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return create_session_factory(get_engine())


def get_session() -> Iterator[Session]:
    with get_session_factory()() as session:
        yield session


@lru_cache
def get_authenticator() -> APIKeyAuthenticator:
    configured = get_settings().api_key_identities_json
    if configured is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is not configured",
        )
    try:
        return APIKeyAuthenticator.from_json(configured.get_secret_value())
    except AuthenticationConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication configuration is invalid",
        ) from exc


def get_principal(
    authenticator: Annotated[APIKeyAuthenticator, Depends(get_authenticator)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> SecurityPrincipal:
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials
        or len(credentials.credentials) > 512
    ):
        authenticator.record_failure("missing_or_malformed_authorization")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return authenticator.authenticate(credentials.credentials)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@lru_cache
def get_tenant_registry() -> TenantSessionRegistry:
    settings = get_settings()
    if settings.tenant_database_urls_json is not None:
        return TenantSessionRegistry.from_database_urls_json(
            settings.tenant_database_urls_json.get_secret_value()
        )
    return TenantSessionRegistry({settings.default_tenant_id: get_session_factory()})


def get_tenant_session(
    principal: Annotated[SecurityPrincipal, Depends(get_principal)],
    tenant_registry: Annotated[TenantSessionRegistry, Depends(get_tenant_registry)],
) -> Iterator[Session]:
    try:
        factory = tenant_registry.session_factory(principal)
    except TenantAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="tenant access denied",
        ) from exc
    with factory() as session:
        yield session


def get_webhook_verifier() -> WebhookVerifier:
    settings = get_settings()
    if settings.webhook_secret is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="refund event webhook is not configured",
        )
    return WebhookVerifier(
        settings.webhook_secret.get_secret_value(),
        tolerance_seconds=settings.webhook_tolerance_seconds,
    )


@lru_cache
def get_tenant_webhook_registry() -> TenantWebhookRegistry:
    settings = get_settings()
    try:
        if settings.webhook_secrets_json is not None:
            return TenantWebhookRegistry.from_json(
                settings.webhook_secrets_json.get_secret_value(),
                get_tenant_registry(),
                tolerance_seconds=settings.webhook_tolerance_seconds,
            )
        if settings.webhook_secret is not None:
            return TenantWebhookRegistry(
                {settings.default_tenant_id: settings.webhook_secret.get_secret_value()},
                get_tenant_registry(),
                tolerance_seconds=settings.webhook_tolerance_seconds,
            )
    except WebhookTenantConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="webhook configuration is invalid",
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="refund event webhook is not configured",
    )
