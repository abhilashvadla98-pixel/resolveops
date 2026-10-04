from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from resolveops.api.dependencies import get_principal, get_tenant_session
from resolveops.api.main import app
from resolveops.database.base import Base
from resolveops.database.employee_it_records import (
    EnterpriseIdentityRecord,
    GitRepositoryAccessRecord,
    ITAccessApprovalDecisionRecord,
    ITAccessCaseRecord,
    ITAccessRequestRecord,
    TeamRecord,
)
from resolveops.database.seed import seed_additional_it_cases, seed_all
from resolveops.employee_it.models import IdentityStatus
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.knowledge.ingestion import ingest_directory
from resolveops.operations.models import ActorRole
from resolveops.security.models import SecurityPrincipal


@pytest.fixture
def it_api() -> Iterator[tuple[TestClient, dict[str, SecurityPrincipal], Engine]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_all(session)
        seed_additional_it_cases(session)
        session.add(
            EnterpriseIdentityRecord(
                identity_id="IDENTITY-MANAGER",
                employee_id="EMP-2000",
                username="anika.rao",
                status=IdentityStatus.ACTIVE,
                mfa_enrolled=True,
            )
        )
        ingest_directory(
            session,
            Path("domain_packs/employee_it/policies"),
            FeatureHashEmbeddingProvider(dimensions=128),
            ingested_at=datetime.now(UTC),
        )
        session.commit()
    current = {
        "principal": SecurityPrincipal(
            subject_id="IDENTITY-2001", tenant_id="TENANT-TEST", role=ActorRole.OPERATOR
        )
    }

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_tenant_session] = session_override
    app.dependency_overrides[get_principal] = lambda: current["principal"]
    with TestClient(app) as client:
        yield client, current, engine
    app.dependency_overrides.clear()
    engine.dispose()


def use_actor(current: dict[str, SecurityPrincipal], subject: str, *, demo: bool = False) -> None:
    current["principal"] = SecurityPrincipal(
        subject_id=subject,
        tenant_id="TENANT-TEST",
        role=ActorRole.APPROVER,
        authentication_method="demo_session" if demo else "api_key",
    )


def request_body(message_id: str = "EMPLOYEE-MSG-1") -> dict[str, str]:
    return {
        "source_message_id": message_id,
        "repository_id": "REPO-ML-PLATFORM",
        "requested_level": "write",
        "justification": "Implement the assigned model-serving endpoint.",
    }


def test_new_request_binds_identity_deduplicates_and_finishes(
    it_api: tuple[TestClient, dict[str, SecurityPrincipal], Engine],
) -> None:
    client, current, engine = it_api
    options = client.get("/api/v1/it/request-options").json()
    assert [item["employee_id"] for item in options["employees"]] == ["EMP-2001"]
    assert options["execution_mode"] == "deterministic"
    first = client.post("/api/v1/it/requests", json=request_body())
    assert first.status_code == 201
    case_id = first.json()["access_case"]["case_id"]
    assert first.json()["employee"]["employee_id"] == "EMP-2001"
    again = client.post("/api/v1/it/requests", json=request_body())
    assert again.json()["access_case"]["case_id"] == case_id
    conflict = client.post(
        "/api/v1/it/requests", json={**request_body(), "requested_level": "read"}
    )
    assert conflict.status_code == 409
    use_actor(current, "IDENTITY-MANAGER")
    approved = client.post(
        f"/api/v1/it/approvals/{case_id}/decision",
        json={"decision": "approve", "note": "Assigned to this repository project."},
    )
    assert approved.status_code == 200
    assert approved.json()["decided_by"] == "IDENTITY-MANAGER"
    assert approved.json()["decision_mode"] == "authenticated_manager"
    completed = client.post(f"/api/v1/it/cases/{case_id}/execute")
    assert completed.status_code == 200
    assert completed.json()["outcome"] == "access_verified"
    with Session(engine) as session:
        assert (
            session.scalar(select(func.count(GitRepositoryAccessRecord.access_id))) == 2
        )  # includes seeded fulfilled request
        assert (
            session.get(
                ITAccessRequestRecord, first.json()["access_request"]["access_request_id"]
            ).approved_by
            == "EMP-2000"
        )


@pytest.mark.parametrize("subject", ["GENERIC-APPROVER", "EMP-2000", "IDENTITY-2001"])
def test_unmapped_or_wrong_manager_cannot_approve(
    it_api: tuple[TestClient, dict[str, SecurityPrincipal], Engine], subject: str
) -> None:
    client, current, engine = it_api
    use_actor(current, subject)
    response = client.post(
        "/api/v1/it/approvals/ITCASE-2002/decision",
        json={"decision": "approve", "note": "Approve request."},
    )
    assert response.status_code == 403
    with Session(engine) as session:
        assert session.get(ITAccessRequestRecord, "ACCESS-REQUEST-2002").approved_by is None
        assert session.scalar(select(func.count(ITAccessApprovalDecisionRecord.approval_id))) == 0


def test_self_approval_and_inactive_manager_denied(
    it_api: tuple[TestClient, dict[str, SecurityPrincipal], Engine],
) -> None:
    client, current, engine = it_api
    with Session(engine) as session:
        session.get(TeamRecord, "TEAM-ML-PLATFORM").manager_employee_id = "EMP-2002"
        session.commit()
    use_actor(current, "IDENTITY-2002")
    result = client.post(
        "/api/v1/it/approvals/ITCASE-2002/decision",
        json={"decision": "approve", "note": "Approve my own request."},
    )
    assert result.status_code == 403
    assert "Self-approval" in result.json()["detail"]
    with Session(engine) as session:
        session.get(TeamRecord, "TEAM-ML-PLATFORM").manager_employee_id = "EMP-2000"
        session.get(EnterpriseIdentityRecord, "IDENTITY-MANAGER").mfa_enrolled = False
        session.commit()
    use_actor(current, "IDENTITY-MANAGER")
    result = client.post(
        "/api/v1/it/approvals/ITCASE-2002/decision",
        json={"decision": "approve", "note": "Approve request."},
    )
    assert result.status_code == 403


def test_demo_impersonation_is_explicit_and_not_available_to_normal_sessions(
    it_api: tuple[TestClient, dict[str, SecurityPrincipal], Engine],
) -> None:
    client, current, _engine = it_api
    forged = client.post(
        "/api/v1/it/requests", json={**request_body(), "demo_employee_id": "EMP-2002"}
    )
    assert forged.status_code == 403
    use_actor(current, "DEMO-USER", demo=True)
    created = client.post(
        "/api/v1/it/requests", json={**request_body(), "demo_employee_id": "EMP-2002"}
    )
    assert created.status_code == 201
    case_id = created.json()["access_case"]["case_id"]
    approved = client.post(
        f"/api/v1/it/approvals/{case_id}/decision",
        json={"decision": "approve", "note": "Synthetic manager approves sandbox access."},
    )
    assert approved.status_code == 200
    assert approved.json()["decided_by"] == "DEMO-MANAGER:EMP-2000"
    assert approved.json()["decision_mode"] == "demo_manager_simulation"


def test_mfa_recovery_retains_attempts_and_latest_result(
    it_api: tuple[TestClient, dict[str, SecurityPrincipal], Engine],
) -> None:
    client, _current, engine = it_api
    first = client.post("/api/v1/it/cases/ITCASE-2004/execute").json()
    assert first["error_code"] == "mfa_required"
    with Session(engine) as session:
        session.get(EnterpriseIdentityRecord, "IDENTITY-2004").mfa_enrolled = True
        session.commit()
    second = client.post("/api/v1/it/cases/ITCASE-2004/execute").json()
    assert second["outcome"] == "access_verified"
    assert second["workflow_id"] != first["workflow_id"]
    history = client.get("/api/v1/it/cases/ITCASE-2004/workflows").json()
    assert [item["outcome"] for item in history] == ["access_verified", "needs_review"]
    latest = client.get("/api/v1/it/cases/ITCASE-2004/workflow").json()
    assert latest["workflow_id"] == second["workflow_id"]
    third = client.post("/api/v1/it/cases/ITCASE-2004/execute").json()
    assert third["outcome"] == "already_satisfied"
    with Session(engine) as session:
        assert session.get(ITAccessCaseRecord, "ITCASE-2004").status.value == "resolved"


def test_intake_rejects_unsupported_privilege(
    it_api: tuple[TestClient, dict[str, SecurityPrincipal], Engine],
) -> None:
    client, _current, _engine = it_api
    result = client.post(
        "/api/v1/it/requests", json={**request_body(), "requested_level": "maintain"}
    )
    assert result.status_code == 409
