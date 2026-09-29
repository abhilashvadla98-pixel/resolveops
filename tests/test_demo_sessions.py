from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from resolveops.api.dependencies import (
    get_authenticator,
    get_demo_session_authenticator,
    get_tenant_registry,
)
from resolveops.api.main import app
from resolveops.database.base import Base
from resolveops.database.seed import seed_all
from resolveops.database.session import create_session_factory
from resolveops.security.demo_sessions import DemoSessionAuthenticator, DemoSessionError
from resolveops.security.tenancy import TenantSessionRegistry

NOW = datetime(2026, 9, 29, 16, 0, tzinfo=UTC)
SECRET = "demo-session-test-secret-0123456789abcdef"


@pytest.fixture
def demo_api() -> Iterator[TestClient]:
    engine: Engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory: sessionmaker[Session] = create_session_factory(engine)
    with factory.begin() as session:
        seed_all(session)
    demo_authenticator = DemoSessionAuthenticator(
        SECRET,
        tenant_id="TENANT-DEMO",
        clock=lambda: NOW,
    )
    app.dependency_overrides[get_demo_session_authenticator] = lambda: demo_authenticator
    app.dependency_overrides[get_authenticator] = lambda: None
    app.dependency_overrides[get_tenant_registry] = lambda: TenantSessionRegistry(
        {"TENANT-DEMO": factory}
    )
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    engine.dispose()


def test_demo_session_is_signed_and_restricted_to_synthetic_tenant() -> None:
    authenticator = DemoSessionAuthenticator(
        SECRET,
        tenant_id="TENANT-DEMO",
        clock=lambda: NOW,
    )

    session = authenticator.create()
    principal = authenticator.authenticate(session.access_token)

    assert session.access_token.startswith("demo.")
    assert principal.tenant_id == "TENANT-DEMO"
    assert principal.subject_id.startswith("DEMO-")


def test_demo_session_rejects_tampering() -> None:
    authenticator = DemoSessionAuthenticator(
        SECRET,
        tenant_id="TENANT-DEMO",
        clock=lambda: NOW,
    )
    session = authenticator.create()

    with pytest.raises(DemoSessionError, match="invalid demo session"):
        authenticator.authenticate(f"{session.access_token}changed")


def test_demo_session_expires() -> None:
    clock = {"now": NOW}
    authenticator = DemoSessionAuthenticator(
        SECRET,
        tenant_id="TENANT-DEMO",
        ttl_seconds=300,
        clock=lambda: clock["now"],
    )
    session = authenticator.create()
    clock["now"] = NOW + timedelta(seconds=301)

    with pytest.raises(DemoSessionError, match="expired"):
        authenticator.authenticate(session.access_token)


def test_demo_endpoint_opens_only_the_synthetic_tenant(demo_api: TestClient) -> None:
    created = demo_api.post("/api/v1/demo/session")

    assert created.status_code == 201
    token = created.json()["access_token"]
    case = demo_api.get(
        "/api/v1/cases/CASE-1001",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert case.status_code == 200
    assert case.json()["customer_id"] == "CUST-1001"
