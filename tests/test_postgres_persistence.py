import os
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from resolveops.api.dependencies import get_principal, get_tenant_session
from resolveops.api.main import app
from resolveops.database.action_records import (
    AuditEventRecord,
    OperationRecord,
    ReliabilityEventRecord,
)
from resolveops.database.records import CaseIssueRecord, RefundRecord
from resolveops.database.seed import seed_all
from resolveops.database.session import create_session_factory
from resolveops.database.simulator_store import SimulatorStore
from resolveops.database.store import CustomerOperationsStore
from resolveops.employee_it.store import EmployeeITStore
from resolveops.employee_it.workflow import EmployeeAccessWorkflow
from resolveops.employee_it.workflow_models import (
    EmployeeAccessWorkflowRequest,
    EmployeeWorkflowOutcome,
)
from resolveops.events.models import RefundStatusChangedData, RefundStatusChangedEvent
from resolveops.events.processor import RefundEventProcessor
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.knowledge.evaluation import evaluate_retriever, load_evaluation_cases
from resolveops.knowledge.ingestion import ingest_directory
from resolveops.knowledge.models import RetrievalMethod
from resolveops.knowledge.retrieval import HybridPolicyRetriever, PolicyRetriever
from resolveops.models.case import CaseIssueStatus, CaseIssueType, IssueFinding
from resolveops.models.refund import RefundKind
from resolveops.operations.actions import ActionTools
from resolveops.operations.models import Actor, ActorRole, IssueRefundRequest
from resolveops.reasoning.models import (
    ReasoningAssessment,
    ReasoningConclusion,
    ReasoningContext,
    ReasoningDisposition,
)
from resolveops.security.models import SecurityPrincipal
from resolveops.workflows.checkpointing import open_postgres_checkpointer
from resolveops.workflows.customer_issue import CustomerIssueWorkflow
from resolveops.workflows.lifecycle import WorkflowLifecycleStore
from resolveops.workflows.models import (
    ApprovalDecisionType,
    WorkflowApprovalDecision,
    WorkflowOutcome,
    WorkflowPause,
    WorkflowRequest,
)


@pytest.mark.postgres
def test_postgres_migration_and_seed() -> None:
    database_url = os.getenv("RESOLVEOPS_TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("RESOLVEOPS_TEST_DATABASE_URL is not set")
    if not database_url.startswith("postgresql+psycopg://"):
        pytest.fail("PostgreSQL test URL must use the psycopg driver")

    engine = create_engine(database_url)
    if "test" not in (engine.url.database or "").lower():
        pytest.fail("Refusing to change a PostgreSQL database without 'test' in its name")

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    try:
        command.upgrade(config, "head")
        with Session(engine) as session:
            assert seed_all(session) is True
            session.commit()
            customer_case = CustomerOperationsStore(session).get_case("CASE-1001")
            assert customer_case is not None and len(customer_case.issues) == 2
            policies = SimulatorStore(session).list_effective_policies(
                as_of=customer_case.opened_at
            )
            assert len(policies) == 2

        session_factory = create_session_factory(engine)
        event_receipt = RefundEventProcessor(
            session_factory,
            clock=lambda: datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        ).process(
            RefundStatusChangedEvent(
                event_id="POSTGRES-EVENT-1",
                source="postgres-test-provider",
                occurred_at=datetime(2026, 9, 24, 11, 59, tzinfo=UTC),
                data=RefundStatusChangedData(
                    refund_id="REF-2001",
                    provider_reference="POSTGRES-PROVIDER-REF-1",
                    status="processing",
                ),
            )
        )
        assert event_receipt.status.value == "processed"
        replay_receipt = RefundEventProcessor(session_factory).process(
            RefundStatusChangedEvent(
                event_id="POSTGRES-EVENT-1",
                source="postgres-test-provider",
                occurred_at=datetime(2026, 9, 24, 11, 59, tzinfo=UTC),
                data=RefundStatusChangedData(
                    refund_id="REF-2001",
                    provider_reference="POSTGRES-PROVIDER-REF-1",
                    status="processing",
                ),
            )
        )
        assert replay_receipt.idempotent_replay is True

        embedding_provider = FeatureHashEmbeddingProvider(dimensions=128)
        with session_factory.begin() as session:
            report = ingest_directory(
                session,
                Path("domain_packs/customer_operations/policies"),
                embedding_provider,
                ingested_at=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
            )
            assert report.created_documents == 6
            employee_report = ingest_directory(
                session,
                Path("domain_packs/employee_it/policies"),
                embedding_provider,
                ingested_at=datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
            )
            assert employee_report.created_documents == 1

        with session_factory() as session:
            results = PolicyRetriever(session, embedding_provider).search(
                "two distinct captured payments same amount and currency",
                as_of=datetime(2026, 9, 24, tzinfo=UTC),
                issue_type=CaseIssueType.DUPLICATE_CHARGE,
                top_k=1,
            )
            assert results[0].document_id in {
                "POLICY-DUPLICATE-CHARGE",
                "POLICY-PAYMENT-STATUS",
            }
            metrics = evaluate_retriever(
                HybridPolicyRetriever(session, embedding_provider),
                RetrievalMethod.HYBRID,
                load_evaluation_cases(Path("evals/retrieval/customer_operations.jsonl")),
                as_of=datetime(2026, 9, 24, tzinfo=UTC),
                k=3,
            )
            assert metrics.query_count == 15
            assert metrics.recall_at_k >= 0.9

        with session_factory.begin() as session:
            issue = session.get(CaseIssueRecord, "ISSUE-1001")
            assert issue is not None
            issue.finding = IssueFinding.CONFIRMED
            issue.status = CaseIssueStatus.ACTION_PENDING

        actions = ActionTools(session_factory)
        refund_request = IssueRefundRequest(
            idempotency_key="postgres-refund-key",
            case_id="CASE-1001",
            issue_id="ISSUE-1001",
            payment_id="PAY-1002",
            amount=Decimal("1499.00"),
            currency="USD",
            kind=RefundKind.DUPLICATE_CHARGE,
            reason="Confirmed duplicate capture in PostgreSQL integration test",
        )
        approver = Actor(actor_id="POSTGRES-APPROVER", role=ActorRole.APPROVER)
        operator = Actor(actor_id="POSTGRES-OPERATOR", role=ActorRole.OPERATOR)

        class PostgresReasoningProvider:
            provider_name = "postgres-test"
            model_name = "scripted-reasoner-v1"

            def assess(self, context: ReasoningContext) -> ReasoningAssessment:
                return ReasoningAssessment(
                    summary="PostgreSQL evidence and policy support the confirmed claim.",
                    conclusion=ReasoningConclusion.CLAIM_SUPPORTED,
                    recommended_disposition=ReasoningDisposition.REFUND_CANDIDATE,
                    supporting_evidence_ids=[context.evidence[0].evidence_id],
                    cited_policy_chunk_ids=[context.policy_excerpts[0].chunk_id],
                    missing_information=[],
                    risk_notes=["Deterministic approval is still required."],
                    rationale="The model advice remains subject to deterministic gates.",
                )

        workflow_request = WorkflowRequest(
            workflow_id="POSTGRES-WORKFLOW-1",
            case_id="CASE-1001",
            issue_id="ISSUE-1001",
            actor=operator,
            refund_request=refund_request,
        )
        lifecycle = WorkflowLifecycleStore(session_factory)
        with open_postgres_checkpointer(database_url) as checkpointer:
            paused = CustomerIssueWorkflow(
                session_factory,
                embedding_provider,
                action_tools=actions,
                reasoning_provider=PostgresReasoningProvider(),
                checkpointer=checkpointer,
                lifecycle_store=lifecycle,
                clock=lambda: datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
            ).start(workflow_request)
        assert isinstance(paused, WorkflowPause)

        with open_postgres_checkpointer(database_url, setup=False) as checkpointer:
            workflow_result = CustomerIssueWorkflow(
                session_factory,
                embedding_provider,
                action_tools=actions,
                reasoning_provider=PostgresReasoningProvider(),
                checkpointer=checkpointer,
                lifecycle_store=WorkflowLifecycleStore(session_factory),
                clock=lambda: datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
            ).resume(
                WorkflowApprovalDecision(
                    approval_id=paused.approval.approval_id,
                    decision=ApprovalDecisionType.APPROVE,
                    actor=approver,
                    note="PostgreSQL restart test approval.",
                )
            )
        assert not isinstance(workflow_result, WorkflowPause)
        assert workflow_result.outcome == WorkflowOutcome.ACTION_VERIFIED
        assert workflow_result.operation is not None
        assert workflow_result.reasoning is not None
        replay_result = actions.issue_refund(refund_request, approver)
        assert replay_result.resource_id == workflow_result.operation.resource_id
        assert replay_result.idempotent_replay is True

        employee_result = EmployeeAccessWorkflow(
            session_factory,
            embedding_provider,
            action_tools=actions,
            clock=lambda: datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        ).run(
            EmployeeAccessWorkflowRequest(
                workflow_id="POSTGRES-EMPLOYEE-WORKFLOW-1",
                case_id="ITCASE-2001",
                actor=operator,
            )
        )
        assert employee_result.outcome == EmployeeWorkflowOutcome.ACCESS_VERIFIED
        assert employee_result.operation is not None and employee_result.operation.verified
        with session_factory() as session:
            employee_snapshot = EmployeeITStore(session).get_snapshot("ITCASE-2001")
            assert employee_snapshot.repository_access is not None
            assert employee_snapshot.group_membership is not None

        with session_factory() as session:
            assert session.get(RefundRecord, workflow_result.operation.resource_id) is not None
            audit_events = list(
                session.scalars(
                    select(AuditEventRecord).where(
                        AuditEventRecord.operation_id == workflow_result.operation.operation_id
                    )
                )
            )
            assert len(audit_events) == 4
            operation = session.get(OperationRecord, workflow_result.operation.operation_id)
            assert operation is not None and operation.attempt_count == 1
            reliability_events = list(
                session.scalars(
                    select(ReliabilityEventRecord).where(
                        ReliabilityEventRecord.operation_id
                        == workflow_result.operation.operation_id
                    )
                )
            )
            assert len(reliability_events) >= 3

        def postgres_session() -> Iterator[Session]:
            with Session(engine) as session:
                yield session

        app.dependency_overrides[get_tenant_session] = postgres_session
        app.dependency_overrides[get_principal] = lambda: SecurityPrincipal(
            subject_id="POSTGRES-APPROVER",
            tenant_id="TENANT-POSTGRES-TEST",
            role=ActorRole.APPROVER,
        )
        with TestClient(app) as client:
            response = client.get("/simulator/v1/cases/CASE-1001")
            assert response.status_code == 200
            assert len(response.json()["issues"]) == 2
    finally:
        app.dependency_overrides.clear()
        command.downgrade(config, "base")
        engine.dispose()
