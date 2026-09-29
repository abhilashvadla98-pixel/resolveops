from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from resolveops.api.dependencies import get_principal, get_tenant_session
from resolveops.api.main import app
from resolveops.database.base import Base
from resolveops.database.records import CaseIssueRecord
from resolveops.database.seed import seed_all
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.knowledge.ingestion import ingest_directory
from resolveops.models.case import CaseIssueStatus, IssueFinding
from resolveops.operations.models import ActorRole
from resolveops.security.models import SecurityPrincipal


@pytest.fixture
def operations_api() -> Iterator[tuple[TestClient, dict[str, ActorRole], Engine]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_all(session)
        ingest_directory(
            session,
            Path("domain_packs/customer_operations/policies"),
            FeatureHashEmbeddingProvider(dimensions=128),
            ingested_at=datetime(2026, 9, 29, 12, 0, tzinfo=UTC),
        )
        session.commit()

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    role = {"value": ActorRole.OPERATOR}
    app.dependency_overrides[get_tenant_session] = test_session
    app.dependency_overrides[get_principal] = lambda: SecurityPrincipal(
        subject_id=f"TEST-{role['value'].value.upper()}",
        tenant_id="TENANT-TEST",
        role=role["value"],
    )
    with TestClient(app) as client:
        yield client, role, engine
    app.dependency_overrides.clear()
    engine.dispose()


def test_complaint_intake_case_list_and_timeline(
    operations_api: tuple[TestClient, dict[str, ActorRole], Engine],
) -> None:
    client, _role, _engine = operations_api
    created = client.post(
        "/api/v1/cases",
        json={
            "customer_id": "CUST-1001",
            "order_id": "ORD-48391",
            "complaint": "I returned my order and still have no refund. I was charged twice.",
        },
    )

    assert created.status_code == 201
    customer_case = created.json()
    assert customer_case["complaint_text"].startswith("I returned")
    assert [issue["issue_type"] for issue in customer_case["issues"]] == [
        "duplicate_charge",
        "missing_return_refund",
    ]
    listed = client.get("/api/v1/cases")
    assert listed.status_code == 200
    assert customer_case["case_id"] in [item["case_id"] for item in listed.json()]

    timeline = client.get(f"/api/v1/cases/{customer_case['case_id']}/timeline")
    assert timeline.status_code == 200
    assert [event["event_type"] for event in timeline.json()][:3] == [
        "complaint_received",
        "issue_classified",
        "issue_classified",
    ]


def test_workflow_approval_can_be_listed_and_resumed(
    operations_api: tuple[TestClient, dict[str, ActorRole], Engine],
) -> None:
    client, role, engine = operations_api
    with Session(engine) as session:
        issue = session.get(CaseIssueRecord, "ISSUE-1001")
        assert issue is not None
        issue.finding = IssueFinding.CONFIRMED
        issue.status = CaseIssueStatus.ACTION_PENDING
        session.commit()
    started = client.post(
        "/api/v1/workflows",
        json={
            "workflow_id": "WORKFLOW-API-1001",
            "case_id": "CASE-1001",
            "issue_id": "ISSUE-1001",
            "refund_request": {
                "idempotency_key": "api-refund-1001",
                "case_id": "CASE-1001",
                "issue_id": "ISSUE-1001",
                "payment_id": "PAY-1002",
                "amount": str(Decimal("1499.00")),
                "currency": "USD",
                "kind": "duplicate_charge",
                "reason": "Confirmed duplicate charge",
            },
        },
    )

    assert started.status_code == 201
    pause = started.json()
    assert pause["status"] == "waiting_approval", started.text
    approvals = client.get("/api/v1/approvals?status=pending")
    assert approvals.status_code == 200
    assert [item["approval_id"] for item in approvals.json()] == [
        pause["approval"]["approval_id"]
    ]

    role["value"] = ActorRole.APPROVER
    decided = client.post(
        f"/api/v1/approvals/{pause['approval']['approval_id']}/decision",
        json={"decision": "approve", "note": "Evidence and policy support the refund."},
    )

    assert decided.status_code == 200
    assert decided.json()["outcome"] == "action_verified"
    final_response = client.get("/api/v1/workflows/WORKFLOW-API-1001/response")
    assert final_response.status_code == 200
    assert "independently verified" in final_response.json()["message"]
    assert "complete" not in final_response.json()["message"].lower()
    events = client.get("/api/v1/workflows/WORKFLOW-API-1001/events")
    assert events.status_code == 200
    assert [event["event_type"] for event in events.json()] == [
        "started",
        "approval_requested",
        "approval_approved",
        "completed",
    ]
