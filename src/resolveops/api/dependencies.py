from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from resolveops.config import get_demo_settings, get_settings
from resolveops.database.session import create_database_engine, create_session_factory
from resolveops.events.webhook import WebhookVerifier
from resolveops.security.authentication import (
    APIKeyAuthenticator,
    AuthenticationConfigurationError,
    AuthenticationError,
)
from resolveops.security.demo_sessions import DemoSessionAuthenticator, DemoSessionError
from resolveops.security.demo_workspaces import (
    DemoWorkspaceCapacityError,
    DemoWorkspaceRegistry,
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
def get_authenticator() -> APIKeyAuthenticator | None:
    configured = get_settings().api_key_identities_json
    if configured is None:
        return None
    raw_configuration = configured.get_secret_value().strip()
    if raw_configuration == "[]":
        return None
    try:
        return APIKeyAuthenticator.from_json(raw_configuration)
    except AuthenticationConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication configuration is invalid",
        ) from exc


@lru_cache
def get_demo_session_authenticator() -> DemoSessionAuthenticator | None:
    settings = get_demo_settings()
    if not settings.demo_enabled or settings.demo_session_secret is None:
        return None
    return DemoSessionAuthenticator(
        settings.demo_session_secret.get_secret_value(),
        tenant_id=settings.demo_tenant_id,
        ttl_seconds=settings.demo_session_ttl_seconds,
    )


def get_principal(
    authenticator: Annotated[APIKeyAuthenticator | None, Depends(get_authenticator)],
    demo_authenticator: Annotated[
        DemoSessionAuthenticator | None, Depends(get_demo_session_authenticator)
    ],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> SecurityPrincipal:
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not credentials.credentials
        or len(credentials.credentials) > 512
    ):
        if authenticator is not None:
            authenticator.record_failure("missing_or_malformed_authorization")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication failed",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = credentials.credentials
    if token.startswith("demo.") and demo_authenticator is not None:
        try:
            return demo_authenticator.authenticate(token)
        except DemoSessionError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication failed",
                headers={"WWW-Authenticate": "Bearer"},
            ) from None
    if authenticator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API authentication is not configured",
        )
    try:
        return authenticator.authenticate(token)
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


@lru_cache
def get_demo_workspace_registry() -> DemoWorkspaceRegistry | None:
    demo_settings = get_demo_settings()
    if not demo_settings.demo_enabled or not demo_settings.demo_isolated_sessions:
        return None
    return DemoWorkspaceRegistry(
        get_engine(),
        ttl_seconds=demo_settings.demo_session_ttl_seconds,
        max_sessions=demo_settings.demo_max_isolated_sessions,
    )


def get_tenant_session(
    principal: Annotated[SecurityPrincipal, Depends(get_principal)],
    tenant_registry: Annotated[TenantSessionRegistry, Depends(get_tenant_registry)],
    demo_workspaces: Annotated[DemoWorkspaceRegistry | None, Depends(get_demo_workspace_registry)],
) -> Iterator[Session]:
    if principal.authentication_method == "demo_session" and demo_workspaces is not None:
        try:
            factory = demo_workspaces.session_factory(principal)
        except DemoWorkspaceCapacityError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The public demo is busy. Please try again shortly.",
            ) from exc
        with factory() as session:
            yield session
        return
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
