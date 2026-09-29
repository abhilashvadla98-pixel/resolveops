import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from resolveops.api.dependencies import get_tenant_webhook_registry
from resolveops.api.main import app
from resolveops.database.base import Base
from resolveops.database.event_records import InboundEventRecord, ResourceEventCursorRecord
from resolveops.database.records import RefundRecord
from resolveops.database.seed import seed_all
from resolveops.database.session import create_session_factory
from resolveops.events.models import InboundEventStatus
from resolveops.events.webhook import WebhookVerifier
from resolveops.models.refund import RefundStatus
from resolveops.security.tenancy import TenantSessionRegistry
from resolveops.security.webhooks import TenantWebhookRegistry

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
SECRET = "test-webhook-secret-with-at-least-32-characters"
TENANT_ID = "TENANT-EVENT-TEST"


@pytest.fixture
def event_api() -> Iterator[tuple[TestClient, sessionmaker[Session], WebhookVerifier]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory.begin() as session:
        seed_all(session)
    verifier = WebhookVerifier(SECRET, clock=lambda: NOW)
    webhook_registry = TenantWebhookRegistry(
        {TENANT_ID: SECRET},
        TenantSessionRegistry({TENANT_ID: factory}),
        clock=lambda: NOW,
    )
    app.dependency_overrides[get_tenant_webhook_registry] = lambda: webhook_registry
    with TestClient(app) as client:
        yield client, factory, verifier
    app.dependency_overrides.clear()
    engine.dispose()


def event_body(
    *,
    event_id: str = "EVT-1001",
    status: str = "processing",
    occurred_at: datetime = NOW,
    completed_at: datetime | None = None,
) -> bytes:
    payload = {
        "event_id": event_id,
        "event_type": "refund.status_changed",
        "source": "payment-provider-sandbox",
        "occurred_at": occurred_at.isoformat(),
        "data": {
            "refund_id": "REF-2001",
            "provider_reference": "PROVIDER-REF-2001",
            "status": status,
            "completed_at": completed_at.isoformat() if completed_at else None,
        },
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def signed_headers(
    verifier: WebhookVerifier, body: bytes, *, timestamp: int | None = None
) -> dict[str, str]:
    signed_at = timestamp if timestamp is not None else int(NOW.timestamp())
    return {
        "X-ResolveOps-Timestamp": str(signed_at),
        "X-ResolveOps-Signature": verifier.sign(body, signed_at),
        "X-ResolveOps-Tenant": TENANT_ID,
        "Content-Type": "application/json",
    }


def test_authenticated_refund_event_updates_state_and_cursor(
    event_api: tuple[TestClient, sessionmaker[Session], WebhookVerifier],
) -> None:
    client, factory, verifier = event_api
    body = event_body()

    response = client.post(
        "/events/v1/refund-status", content=body, headers=signed_headers(verifier, body)
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"
    assert response.json()["idempotent_replay"] is False
    with factory() as session:
        refund = session.get(RefundRecord, "REF-2001")
        cursor = session.get(ResourceEventCursorRecord, ("refund", "REF-2001"))
        assert refund is not None and refund.status == RefundStatus.PROCESSING
        assert cursor is not None and cursor.last_event_id == "EVT-1001"


def test_identical_event_is_idempotent_but_changed_payload_conflicts(
    event_api: tuple[TestClient, sessionmaker[Session], WebhookVerifier],
) -> None:
    client, factory, verifier = event_api
    body = event_body()
    headers = signed_headers(verifier, body)
    assert client.post("/events/v1/refund-status", content=body, headers=headers).status_code == 200

    replay = client.post("/events/v1/refund-status", content=body, headers=headers)
    changed = event_body(status="failed")
    conflict = client.post(
        "/events/v1/refund-status",
        content=changed,
        headers=signed_headers(verifier, changed),
    )

    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "event_id_conflict"
    with factory() as session:
        count = session.scalar(select(func.count()).select_from(InboundEventRecord))
        assert count == 1


@pytest.mark.parametrize("authentication", ["bad_signature", "expired"])
def test_authentication_failures_do_not_store_events(
    event_api: tuple[TestClient, sessionmaker[Session], WebhookVerifier],
    authentication: str,
) -> None:
    client, factory, verifier = event_api
    body = event_body()
    if authentication == "bad_signature":
        headers = signed_headers(verifier, body)
        headers["X-ResolveOps-Signature"] = f"sha256={'0' * 64}"
    else:
        headers = signed_headers(verifier, body, timestamp=int(NOW.timestamp()) - 301)

    response = client.post("/events/v1/refund-status", content=body, headers=headers)

    assert response.status_code == 401
    with factory() as session:
        count = session.scalar(select(func.count()).select_from(InboundEventRecord))
        assert count == 0


def test_stale_event_is_stored_without_regressing_refund(
    event_api: tuple[TestClient, sessionmaker[Session], WebhookVerifier],
) -> None:
    client, factory, verifier = event_api
    newer = event_body(event_id="EVT-NEW", occurred_at=NOW + timedelta(seconds=2))
    older = event_body(
        event_id="EVT-OLD",
        status="failed",
        occurred_at=NOW + timedelta(seconds=1),
    )
    assert (
        client.post(
            "/events/v1/refund-status", content=newer, headers=signed_headers(verifier, newer)
        ).status_code
        == 200
    )

    response = client.post(
        "/events/v1/refund-status", content=older, headers=signed_headers(verifier, older)
    )

    assert response.status_code == 200
    assert response.json()["status"] == InboundEventStatus.IGNORED_STALE
    with factory() as session:
        refund = session.get(RefundRecord, "REF-2001")
        assert refund is not None and refund.status == RefundStatus.PROCESSING


def test_terminal_refund_cannot_be_regressed_by_newer_event(
    event_api: tuple[TestClient, sessionmaker[Session], WebhookVerifier],
) -> None:
    client, factory, verifier = event_api
    completed_at = NOW + timedelta(seconds=1)
    completed = event_body(
        event_id="EVT-COMPLETE",
        status="completed",
        occurred_at=completed_at,
        completed_at=completed_at,
    )
    regressive = event_body(
        event_id="EVT-REGRESS",
        status="processing",
        occurred_at=NOW + timedelta(seconds=2),
    )
    assert (
        client.post(
            "/events/v1/refund-status",
            content=completed,
            headers=signed_headers(verifier, completed),
        ).status_code
        == 200
    )

    response = client.post(
        "/events/v1/refund-status",
        content=regressive,
        headers=signed_headers(verifier, regressive),
    )

    assert response.status_code == 200
    assert response.json()["status"] == InboundEventStatus.REJECTED
    with factory() as session:
        refund = session.get(RefundRecord, "REF-2001")
        assert refund is not None and refund.status == RefundStatus.COMPLETED


def test_invalid_event_schema_is_rejected_before_storage(
    event_api: tuple[TestClient, sessionmaker[Session], WebhookVerifier],
) -> None:
    client, factory, verifier = event_api
    body = event_body(status="completed")

    response = client.post(
        "/events/v1/refund-status", content=body, headers=signed_headers(verifier, body)
    )

    assert response.status_code == 422
    with factory() as session:
        count = session.scalar(select(func.count()).select_from(InboundEventRecord))
        assert count == 0
