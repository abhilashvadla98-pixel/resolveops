from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from resolveops.api.dependencies import get_principal, get_tenant_session
from resolveops.api.main import app
from resolveops.config import Settings
from resolveops.database.base import Base
from resolveops.database.employee_it_records import EnterpriseIdentityRecord
from resolveops.database.event_records import InboundEventRecord
from resolveops.database.records import CaseMessageRecord, RefundRecord
from resolveops.database.seed import seed_additional_it_cases, seed_all
from resolveops.database.session import create_session_factory
from resolveops.employee_it.models import IdentityStatus
from resolveops.jobs.store import AgentJobStore
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.knowledge.ingestion import ingest_directory
from resolveops.operations.models import ActorRole
from resolveops.security.models import SecurityPrincipal


@pytest.fixture
def operations_api(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[TestClient, dict[str, ActorRole], Engine]]:
    # Exercise the control plane without inheriting an owner's live-provider settings.
    monkeypatch.setenv("RESOLVEOPS_INTEGRATED_AGENTS_ENABLED", "false")
    monkeypatch.setenv("RESOLVEOPS_AGENT_QUEUE_ENABLED", "false")
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        seed_all(session)
        session.add(
            EnterpriseIdentityRecord(
                identity_id="TEST-APPROVER",
                employee_id="EMP-2000",
                username="test.manager",
                status=IdentityStatus.ACTIVE,
                mfa_enrolled=True,
            )
        )
        ingest_directory(
            session,
            Path("domain_packs/customer_operations/policies"),
            FeatureHashEmbeddingProvider(dimensions=128),
            ingested_at=datetime(2026, 9, 29, 12, 0, tzinfo=UTC),
        )
        ingest_directory(
            session,
            Path("domain_packs/employee_it/policies"),
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


def test_agent_run_trace_endpoint_is_tenant_scoped(
    operations_api: tuple[TestClient, dict[str, ActorRole], Engine],
) -> None:
    client, _role, _engine = operations_api
    response = client.get("/api/v1/agent-workflows/WF-NOT-RUN/runs")
    assert response.status_code == 200
    assert response.json() == []


def test_disabled_inference_blocks_legacy_analysis_even_with_a_saved_key(
    operations_api: tuple[TestClient, dict[str, ActorRole], Engine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _role, _engine = operations_api
    configured = Settings(
        database_url=SecretStr("sqlite://"),
        gemini_api_key=SecretStr("synthetic-test-key"),
        gemini_key_rotated=True,
        integrated_agents_enabled=False,
    )
    monkeypatch.setattr("resolveops.api.agents.get_settings", lambda: configured)

    def forbidden_runtime(*args: object, **kwargs: object) -> None:
        raise AssertionError("Disabled inference must not build a provider runtime")

    monkeypatch.setattr("resolveops.api.agents.build_agent_runtime", forbidden_runtime)
    response = client.post(
        "/api/v1/agent-workflows",
        json={
            "workflow_id": "DISABLED-AI",
            "case_id": "CASE-1001",
            "domain": "customer_operations",
            "objective": "Investigate this complaint.",
        },
    )
    assert response.status_code == 503


def test_agent_job_api_is_idempotent_tenant_scoped_and_streams_terminal_events(
    operations_api: tuple[TestClient, dict[str, ActorRole], Engine],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _role, engine = operations_api
    configured = Settings(
        database_url=SecretStr("sqlite://"),
        gemini_api_key=SecretStr("synthetic-test-key"),
        agent_queue_enabled=True,
        agent_job_max_attempts=1,
    )
    monkeypatch.setattr("resolveops.api.agents.get_settings", lambda: configured)
    payload = {
        "workflow_id": "AGENT-JOB-API",
        "case_id": "CASE-1001",
        "domain": "customer_operations",
        "objective": "Investigate the case using trusted evidence.",
        "idempotency_key": "AGENT-JOB-API-KEY",
    }

    created = client.post("/api/v1/agent-workflows/jobs", json=payload)
    replay = client.post("/api/v1/agent-workflows/jobs", json=payload)

    assert created.status_code == replay.status_code == 202
    assert created.json()["job_id"] == replay.json()["job_id"]
    job_id = created.json()["job_id"]
    store = AgentJobStore(create_session_factory(engine))
    claimed = store.claim_next("TEST-WORKER")
    assert claimed is not None
    store.fail(job_id, "TEST-WORKER", "synthetic_provider_failure")

    saved = client.get(f"/api/v1/agent-workflows/jobs/{job_id}")
    streamed = client.get(f"/api/v1/agent-workflows/jobs/{job_id}/events")

    assert saved.status_code == 200
    assert saved.json()["status"] == "dead_letter"
    assert streamed.status_code == 200
    assert "event: queued" in streamed.text
    assert "event: dead_lettered" in streamed.text


def test_operator_queues_audit_and_feedback_use_persisted_records(
    operations_api: tuple[TestClient, dict[str, ActorRole], Engine],
) -> None:
    client, role, _engine = operations_api

    queue = client.get("/api/v1/case-queue", params={"query": "CASE-1001", "page_size": 10})
    assert queue.status_code == 200
    assert queue.json()["total"] == 1
    assert queue.json()["items"][0]["case_id"] == "CASE-1001"

    it_queue = client.get("/api/v1/it/cases", params={"page_size": 10})
    assert it_queue.status_code == 200
    assert it_queue.json()["total"] == 1
    assert it_queue.json()["items"][0]["case_id"] == "ITCASE-2001"

    submitted = client.post(
        "/api/v1/feedback",
        json={
            "case_id": "CASE-1001",
            "kind": "classification_correction",
            "original_value": {"issue_type": "duplicate_charge"},
            "corrected_value": {"issue_type": "authorization_hold"},
            "reason": "The second payment was authorized but never captured.",
            "model_provider": "offline",
            "model_name": "scripted",
            "prompt_version": "intake-v1",
        },
    )
    assert submitted.status_code == 201
    feedback = submitted.json()
    assert feedback["review_status"] == "pending"
    assert feedback["dataset_example_id"] is None

    role["value"] = ActorRole.APPROVER
    reviewed = client.post(
        f"/api/v1/feedback/{feedback['feedback_id']}/review",
        json={"status": "reviewed", "note": "Payment state supports the correction."},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["review_status"] == "reviewed"
    assert reviewed.json()["dataset_example_id"] is None

    audit = client.get("/api/v1/audit/events", params={"case_id": "CASE-1001"})
    assert audit.status_code == 200
    assert all(item["case_id"] == "CASE-1001" for item in audit.json())


def test_employee_access_api_executes_verifies_and_replays_safely(
    operations_api: tuple[TestClient, dict[str, ActorRole], Engine],
) -> None:
    client, _role, _engine = operations_api

    first = client.post("/api/v1/it/cases/ITCASE-2001/execute")

    assert first.status_code == 200
    result = first.json()
    assert result["outcome"] == "access_verified"
    assert result["decision"] == "grant_access"
    assert result["verified_access_id"]
    assert result["operation"]["verified"] is True
    assert result["node_history"][-3:] == ["grant_access", "verify_access", "complete"]
    snapshot = client.get("/simulator/v1/it/cases/ITCASE-2001")
    assert snapshot.status_code == 200
    assert snapshot.json()["access_case"]["status"] == "resolved"
    assert snapshot.json()["access_request"]["status"] == "fulfilled"
    assert snapshot.json()["repository_access"]["status"] == "active"
    stored = client.get("/api/v1/it/cases/ITCASE-2001/workflow")
    assert stored.status_code == 200
    assert stored.json()["outcome"] == "access_verified"
    assert stored.json()["verified_access_id"] == result["verified_access_id"]

    replay = client.post("/api/v1/it/cases/ITCASE-2001/execute")
    assert replay.status_code == 200
    assert replay.json()["outcome"] == "already_satisfied"
    assert replay.json()["decision"] == "no_action"
    stored_after_replay = client.get("/api/v1/it/cases/ITCASE-2001/workflow")
    assert stored_after_replay.json()["outcome"] == "already_satisfied"
    history = client.get("/api/v1/it/cases/ITCASE-2001/workflows").json()
    assert [item["outcome"] for item in history] == ["already_satisfied", "access_verified"]


def test_pending_it_request_can_be_approved_then_processed(
    operations_api: tuple[TestClient, dict[str, ActorRole], Engine],
) -> None:
    client, role, engine = operations_api
    with Session(engine) as session:
        assert seed_additional_it_cases(session) is True
        session.commit()

    approvals = client.get("/api/v1/it/approvals")
    assert approvals.status_code == 200
    assert [item["case_id"] for item in approvals.json()] == ["ITCASE-2002"]
    assert approvals.json()[0]["status"] == "pending"

    role["value"] = ActorRole.APPROVER
    decision = client.post(
        "/api/v1/it/approvals/ITCASE-2002/decision",
        json={
            "decision": "approve",
            "note": "Manager confirmed the project assignment and least-privilege access.",
        },
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "approved"
    assert decision.json()["manager_employee_id"] == "EMP-2000"

    role["value"] = ActorRole.OPERATOR
    processed = client.post("/api/v1/it/cases/ITCASE-2002/execute")
    assert processed.status_code == 200
    assert processed.json()["outcome"] == "access_verified"
    assert processed.json()["verified_access_id"]

    decided = client.get("/api/v1/it/approvals")
    assert decided.status_code == 200
    assert decided.json()[0]["decision_note"].startswith("Manager confirmed")
    audit = client.get("/api/v1/audit/events", params={"case_id": "ITCASE-2002"})
    assert audit.status_code == 200
    assert any(
        item["event_type"] == "approval_approved"
        and item["workflow_or_operation_id"] == "IT-APPROVAL-ITCASE-2002"
        for item in audit.json()
    )


def test_it_safety_stop_is_persisted_and_auditable(
    operations_api: tuple[TestClient, dict[str, ActorRole], Engine],
) -> None:
    client, _role, engine = operations_api
    with Session(engine) as session:
        assert seed_additional_it_cases(session) is True
        session.commit()

    result = client.post("/api/v1/it/cases/ITCASE-2004/execute")
    assert result.status_code == 200
    assert result.json()["status"] == "escalated"
    assert result.json()["outcome"] == "needs_review"
    assert result.json()["error_code"] == "mfa_required"

    stored = client.get("/api/v1/it/cases/ITCASE-2004/workflow")
    assert stored.status_code == 200
    assert stored.json()["error_code"] == "mfa_required"
    snapshot = client.get("/simulator/v1/it/cases/ITCASE-2004")
    assert snapshot.json()["access_case"]["status"] == "escalated"
    assert snapshot.json()["repository_access"] is None
    audit = client.get("/api/v1/audit/events", params={"case_id": "ITCASE-2004"})
    assert any(
        item["event_type"] == "it_workflow_escalated" and item["result"] == "needs_review"
        for item in audit.json()
    )


def test_workflow_approval_can_be_listed_and_resumed(
    operations_api: tuple[TestClient, dict[str, ActorRole], Engine],
) -> None:
    client, role, engine = operations_api
    created = client.post(
        "/api/v1/cases",
        json={
            "customer_id": "CUST-1001",
            "order_id": "ORD-48391",
            "complaint": "I was charged twice.",
            "source_message_id": "CUSTOMER-NEW-DUPLICATE-1",
        },
    )
    assert created.status_code == 201
    new_case = created.json()
    case_id = new_case["case_id"]
    issue_id = new_case["issues"][0]["issue_id"]
    assert new_case["issues"][0]["finding"] == "undetermined"
    with Session(engine) as session:
        refund_count_before = session.scalar(select(func.count(RefundRecord.refund_id)))
    started = client.post(
        "/api/v1/workflows",
        json={
            "workflow_id": "WORKFLOW-API-1001",
            "case_id": case_id,
            "issue_id": issue_id,
        },
    )

    assert started.status_code == 201
    pause = started.json()
    assert pause["status"] == "waiting_approval", started.text
    waiting_case = client.get(f"/api/v1/cases/{case_id}").json()
    assert waiting_case["status"] == "pending_approval"
    with Session(engine) as session:
        assert session.scalar(select(func.count(RefundRecord.refund_id))) == refund_count_before
    approvals = client.get("/api/v1/approvals?status=pending")
    assert approvals.status_code == 200
    assert [item["approval_id"] for item in approvals.json()] == [pause["approval"]["approval_id"]]

    role["value"] = ActorRole.APPROVER
    decided = client.post(
        f"/api/v1/approvals/{pause['approval']['approval_id']}/decision",
        json={"decision": "approve", "note": "Evidence and policy support the refund."},
    )

    assert decided.status_code == 200
    assert decided.json()["outcome"] == "refund_submitted"
    assert decided.json()["status"] == "waiting_external"
    updated_case = client.get(f"/api/v1/cases/{case_id}").json()
    assert updated_case["status"] == "in_progress"
    duplicate_issue = next(item for item in updated_case["issues"] if item["issue_id"] == issue_id)
    assert duplicate_issue["status"] == "verifying"
    assert duplicate_issue["verification"]["status"] == "pending"
    assert duplicate_issue["resolution"] is None
    with Session(engine) as session:
        refund = session.get(RefundRecord, decided.json()["verified_resource_id"])
        assert refund is not None and refund.status.value == "pending"
    final_response = client.get("/api/v1/workflows/WORKFLOW-API-1001/response")
    assert final_response.status_code == 200
    assert "independently verified" in final_response.json()["message"]
    assert "Settlement is still pending" in final_response.json()["message"]
    events = client.get("/api/v1/workflows/WORKFLOW-API-1001/events")
    assert events.status_code == 200
    event_types = [event["event_type"] for event in events.json()]
    assert event_types.index("payment_evidence_loaded") < event_types.index("approval_requested")
    assert event_types.index("approval_approved") < event_types.index("action_executed")
    assert event_types.index("action_executed") < event_types.index("action_verified")
    reliability = client.get("/api/v1/reliability/summary")
    assert reliability.status_code == 200
    summary = reliability.json()
    assert summary["total_operations"] == 1
    assert summary["outcomes"] == {"completed": 1}
    assert summary["latency_sample_count"] == 1
    assert summary["p50_latency_ms"] is not None
    assert summary["p95_latency_ms"] is not None
    assert summary["failed_operation_count"] == 0
    assert summary["recent_operations"][0]["operation_type"] == "issue_refund"
    assert [event["event_type"] for event in summary["recent_operations"][0]["events"]] == [
        "attempt_started",
        "attempt_succeeded",
        "verification_attempted",
    ]


@pytest.mark.parametrize("actor_role", [ActorRole.OPERATOR, ActorRole.APPROVER, ActorRole.SYSTEM])
def test_demo_settlement_refuses_every_non_demo_principal(
    operations_api: tuple[TestClient, dict[str, ActorRole], Engine],
    actor_role: ActorRole,
) -> None:
    client, role, engine = operations_api
    role["value"] = actor_role
    result = client.post("/api/v1/demo/refunds/REF-2001/status", json={"status": "completed"})
    assert result.status_code == 403
    assert result.json()["detail"] == "demo session required"
    with Session(engine) as session:
        assert session.get(RefundRecord, "REF-2001").status.value == "pending"
        assert session.scalar(select(func.count(InboundEventRecord.event_id))) == 0


@pytest.mark.parametrize("final_status", ["completed", "failed"])
def test_demo_settlement_same_final_is_idempotent_and_conflicting_final_is_denied(
    operations_api: tuple[TestClient, dict[str, ActorRole], Engine],
    final_status: str,
) -> None:
    client, _role, engine = operations_api
    app.dependency_overrides[get_principal] = lambda: SecurityPrincipal(
        subject_id="DEMO-OPERATOR",
        tenant_id="TENANT-TEST",
        role=ActorRole.OPERATOR,
        authentication_method="demo_session",
    )
    endpoint = "/api/v1/demo/refunds/REF-2001/status"
    first = client.post(endpoint, json={"status": final_status})
    replay = client.post(endpoint, json={"status": final_status})
    assert first.status_code == replay.status_code == 200
    assert (
        first.json()
        == replay.json()
        == {
            "status": final_status,
            "mode": "synthetic_provider",
            "refund_id": "REF-2001",
        }
    )
    conflicting = client.post(
        endpoint, json={"status": "failed" if final_status == "completed" else "completed"}
    )
    assert conflicting.status_code == 409
    assert "cannot be overwritten" in conflicting.json()["detail"]
    with Session(engine) as session:
        assert session.get(RefundRecord, "REF-2001").status.value == final_status
        assert session.scalar(select(func.count(InboundEventRecord.event_id))) == 1


def test_client_cannot_choose_refund_target_or_amount(
    operations_api: tuple[TestClient, dict[str, ActorRole], Engine],
) -> None:
    client, _role, engine = operations_api
    with Session(engine) as session:
        count_before = session.scalar(select(func.count(RefundRecord.refund_id)))
    response = client.post(
        "/api/v1/workflows",
        json={
            "workflow_id": "FORGED-REFUND",
            "case_id": "CASE-1001",
            "issue_id": "ISSUE-1001",
            "refund_request": {
                "idempotency_key": "forged-key",
                "case_id": "CASE-1001",
                "issue_id": "ISSUE-1001",
                "payment_id": "PAY-1001",
                "amount": "100.00",
                "currency": "USD",
                "kind": "duplicate_charge",
                "reason": "Client chooses amount",
            },
        },
    )
    assert response.status_code == 422
    with Session(engine) as session:
        assert session.scalar(select(func.count(RefundRecord.refund_id))) == count_before


def test_intake_receipts_and_clarification_continue_one_case(
    operations_api: tuple[TestClient, dict[str, ActorRole], Engine],
) -> None:
    client, _role, engine = operations_api
    body = {
        "customer_id": "CUST-1001",
        "order_id": "ORD-48391",
        "complaint": "My payment looks wrong.",
        "source_message_id": "INTAKE-MSG-1",
    }
    first = client.post("/api/v1/cases", json=body)
    assert first.status_code == 201
    case_id = first.json()["case_id"]
    assert first.json()["intake_status"] == "needs_clarification"
    assert first.json()["issues"] == []
    again = client.post("/api/v1/cases", json=body)
    assert again.json()["case_id"] == case_id
    changed = client.post("/api/v1/cases", json={**body, "complaint": "Different message"})
    assert changed.status_code == 422
    reply = {"source_message_id": "REPLY-MSG-1", "message": "I was charged twice for this order."}
    clarified = client.post(f"/api/v1/cases/{case_id}/messages", json=reply)
    assert clarified.status_code == 200
    assert clarified.json()["case_id"] == case_id
    assert [issue["issue_type"] for issue in clarified.json()["issues"]] == ["duplicate_charge"]
    assert client.post(f"/api/v1/cases/{case_id}/messages", json=reply).json() == clarified.json()
    conflict = client.post(
        f"/api/v1/cases/{case_id}/messages", json={**reply, "message": "Something else"}
    )
    assert conflict.status_code == 422
    messages = client.get(f"/api/v1/cases/{case_id}/messages").json()
    assert [item["source_message_id"] for item in messages] == ["INTAKE-MSG-1", "REPLY-MSG-1"]
    with Session(engine) as session:
        assert (
            session.scalar(
                select(func.count(CaseMessageRecord.message_id)).where(
                    CaseMessageRecord.case_id == case_id
                )
            )
            == 2
        )
