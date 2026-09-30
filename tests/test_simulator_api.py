from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from resolveops.api.dependencies import get_principal, get_tenant_session
from resolveops.api.main import app
from resolveops.database.base import Base
from resolveops.database.seed import seed_all
from resolveops.operations.models import ActorRole
from resolveops.security.models import SecurityPrincipal


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_all(session)
        session.commit()

    def test_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_tenant_session] = test_session
    app.dependency_overrides[get_principal] = lambda: SecurityPrincipal(
        subject_id="TEST-APPROVER",
        tenant_id="TENANT-TEST",
        role=ActorRole.APPROVER,
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.mark.parametrize(
    ("path", "field", "expected"),
    [
        ("/simulator/v1/customers/CUST-1001", "name", "Maya Patel"),
        ("/simulator/v1/orders/ORD-48391", "status", "partially_returned"),
        ("/simulator/v1/returns/RET-3001", "status", "received"),
        ("/simulator/v1/refunds/REF-2001", "kind", "return"),
        ("/simulator/v1/tickets/TKT-4001", "status", "in_progress"),
        ("/simulator/v1/notifications/NOTE-5001", "status", "sent"),
    ],
)
def test_reads_simulated_resources(
    client: TestClient,
    path: str,
    field: str,
    expected: str,
) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.json()[field] == expected


def test_case_exposes_independent_issues(client: TestClient) -> None:
    response = client.get("/simulator/v1/cases/CASE-1001")

    assert response.status_code == 200
    issues = response.json()["issues"]
    assert [issue["issue_type"] for issue in issues] == [
        "duplicate_charge",
        "missing_return_refund",
    ]


def test_lists_order_payments(client: TestClient) -> None:
    response = client.get("/simulator/v1/orders/ORD-48391/payments")

    assert response.status_code == 200
    assert [payment["payment_id"] for payment in response.json()] == [
        "PAY-1001",
        "PAY-1002",
    ]


def test_filters_effective_policies_by_issue_type(client: TestClient) -> None:
    response = client.get(
        "/simulator/v1/policies",
        params={
            "issue_type": "duplicate_charge",
            "as_of": "2026-09-16T15:00:00Z",
        },
    )

    assert response.status_code == 200
    policies = response.json()
    assert [policy["policy_id"] for policy in policies] == ["POLICY-DUPLICATE-CHARGE-V1"]


def test_rejects_policy_time_without_timezone(client: TestClient) -> None:
    response = client.get(
        "/simulator/v1/policies",
        params={"as_of": "2026-09-16T15:00:00"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "as_of must include a timezone"


def test_missing_resource_returns_clear_404(client: TestClient) -> None:
    response = client.get("/simulator/v1/customers/CUST-MISSING")

    assert response.status_code == 404
    assert response.json() == {"detail": "customer CUST-MISSING was not found"}


def test_simulator_routes_are_read_only(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    simulator_paths = {
        path: operations
        for path, operations in schema["paths"].items()
        if path.startswith("/simulator/v1")
    }

    assert simulator_paths
    assert all(set(operations) == {"get"} for operations in simulator_paths.values())


def test_reads_employee_it_case_from_simulator(client: TestClient) -> None:
    response = client.get("/simulator/v1/it/cases/ITCASE-2001")

    assert response.status_code == 200
    payload = response.json()
    assert payload["employee"]["employee_id"] == "EMP-2001"
    assert payload["team"]["name"] == "ML Platform"
    assert payload["repository"]["repository_id"] == "REPO-ML-PLATFORM"
    assert payload["repository_access"] is None


def test_employee_it_simulator_masks_pii_for_agent(client: TestClient) -> None:
    app.dependency_overrides[get_principal] = lambda: SecurityPrincipal(
        subject_id="TEST-AGENT",
        tenant_id="TENANT-TEST",
        role=ActorRole.AGENT,
    )

    response = client.get("/simulator/v1/it/cases/ITCASE-2001")

    assert response.status_code == 200
    payload = response.json()
    assert payload["employee"]["name"] == "D*** C***"
    assert payload["employee"]["work_email"] == "d***@example.com"
    assert payload["identity"]["username"] == "redacted"
    assert payload["git_account"]["username"] == "redacted"


def test_missing_employee_it_case_returns_404(client: TestClient) -> None:
    response = client.get("/simulator/v1/it/cases/ITCASE-MISSING")

    assert response.status_code == 404
    assert response.json() == {"detail": "IT access case ITCASE-MISSING was not found"}
