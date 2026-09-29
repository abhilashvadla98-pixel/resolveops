import re
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from resolveops.api.dependencies import get_tenant_registry
from resolveops.api.main import app
from resolveops.database.health import CURRENT_SCHEMA_REVISION
from resolveops.database.session import create_session_factory
from resolveops.security.tenancy import TenantSessionRegistry

client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert re.fullmatch(r"[a-f0-9]{32}", response.headers["X-ResolveOps-Trace-ID"])


def test_liveness_does_not_require_database() -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


@contextmanager
def readiness_client(revision: str) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": revision},
        )
    registry = TenantSessionRegistry({"TENANT-TEST": create_session_factory(engine)})
    app.dependency_overrides[get_tenant_registry] = lambda: registry
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_readiness_verifies_database_and_schema() -> None:
    with readiness_client(CURRENT_SCHEMA_REVISION) as test_client:
        response = test_client.get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}


def test_readiness_fails_for_outdated_schema() -> None:
    with readiness_client("0007_event_ingestion") as test_client:
        response = test_client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready"}
