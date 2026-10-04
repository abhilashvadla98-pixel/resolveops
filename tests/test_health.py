import re
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.metadata import version as package_version

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from resolveops.api.dependencies import get_tenant_registry
from resolveops.api.main import app
from resolveops.database.health import CURRENT_SCHEMA_REVISION
from resolveops.database.session import create_session_factory
from resolveops.security.tenancy import TenantSessionRegistry

client = TestClient(app)


def test_api_reports_installed_release_version() -> None:
    assert app.version == package_version("resolveops")


def test_health_check() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert re.fullmatch(r"[a-f0-9]{32}", response.headers["X-ResolveOps-Trace-ID"])


def test_liveness_does_not_require_database() -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_build_metadata_is_safe_and_does_not_require_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.delenv("RESOLVEOPS_BUILD_SHA", raising=False)
    monkeypatch.setenv("RESOLVEOPS_GEMINI_API_KEY", "must-not-appear-in-build-metadata")

    response = client.get("/health/build")

    assert response.status_code == 200
    assert response.json() == {
        "version": package_version("resolveops"),
        "required_schema_revision": CURRENT_SCHEMA_REVISION,
        "build_sha": None,
    }
    assert "must-not-appear" not in response.text


@pytest.mark.parametrize("environment_key", ["RENDER_GIT_COMMIT", "RESOLVEOPS_BUILD_SHA"])
@pytest.mark.parametrize("sha_length", [40, 64])
def test_build_metadata_accepts_valid_commit_identity(
    monkeypatch: pytest.MonkeyPatch, environment_key: str, sha_length: int
) -> None:
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.delenv("RESOLVEOPS_BUILD_SHA", raising=False)
    monkeypatch.setenv(environment_key, "AB" * (sha_length // 2))

    response = client.get("/health/build")

    assert response.status_code == 200
    assert response.json()["build_sha"] == "ab" * (sha_length // 2)


@pytest.mark.parametrize(
    "candidate",
    ["a" * 39, "a" * 65, "g" * 40, "a" * 40 + "\n", "/private/path/to/config"],
)
def test_build_metadata_never_echoes_invalid_identity(
    monkeypatch: pytest.MonkeyPatch, candidate: str
) -> None:
    monkeypatch.setenv("RENDER_GIT_COMMIT", candidate)
    monkeypatch.setenv("RESOLVEOPS_BUILD_SHA", "b" * 40)

    response = client.get("/health/build")

    assert response.status_code == 200
    assert response.json()["build_sha"] is None
    assert candidate not in response.text


def test_render_commit_is_authoritative_over_optional_build_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RENDER_GIT_COMMIT", "a" * 40)
    monkeypatch.setenv("RESOLVEOPS_BUILD_SHA", "b" * 40)

    assert client.get("/health/build").json()["build_sha"] == "a" * 40


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
