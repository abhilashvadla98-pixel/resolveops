from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from resolveops.agents.models import MultiAgentReasoningResult
from resolveops.database.action_records import AuditEventRecord, OperationRecord
from resolveops.database.base import Base
from resolveops.database.employee_it_records import (
    DirectoryGroupMembershipRecord,
    EmployeeRecord,
    EmployeeTeamMembershipRecord,
    EnterpriseIdentityRecord,
    GitAccountRecord,
    GitRepositoryAccessRecord,
    ITAccessRequestRecord,
    ITNotificationRecord,
)
from resolveops.database.seed import seed_all
from resolveops.database.session import create_session_factory
from resolveops.employee_it.models import (
    AccessRequestStatus,
    EmploymentStatus,
    GitAccountStatus,
    GrantRepositoryAccessRequest,
    MembershipStatus,
    RepositoryAccessLevel,
)
from resolveops.employee_it.store import EmployeeITStore
from resolveops.employee_it.workflow import EmployeeAccessWorkflow
from resolveops.employee_it.workflow_models import (
    EmployeeAccessWorkflowRequest,
    EmployeeWorkflowDecision,
    EmployeeWorkflowOutcome,
)
from resolveops.evaluation.employee_dataset import load_employee_evaluation_cases
from resolveops.evaluation.employee_workflow import evaluate_employee_workflow_cases
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.knowledge.ingestion import ingest_directory
from resolveops.operations.actions import ActionTools
from resolveops.operations.errors import BusinessRuleError
from resolveops.operations.models import Actor, ActorRole, AuditEventType, OperationType
from resolveops.reasoning.models import (
    ReasoningAssessment,
    ReasoningConclusion,
    ReasoningContext,
    ReasoningDisposition,
)
from resolveops.workflows.models import WorkflowStatus

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
POLICY_DIRECTORY = Path("domain_packs/employee_it/policies")


@pytest.fixture
def employee_database() -> Iterator[tuple[Engine, sessionmaker[Session]]]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory.begin() as session:
        seed_all(session)
        ingest_directory(
            session,
            POLICY_DIRECTORY,
            FeatureHashEmbeddingProvider(dimensions=128),
            ingested_at=NOW,
        )
    yield engine, factory
    engine.dispose()


def ids() -> Callable[[str], str]:
    sequence = iter(range(1, 100))
    return lambda prefix: f"{prefix}-IT-{next(sequence):04d}"


def workflow(
    factory: sessionmaker[Session],
    *,
    role: ActorRole = ActorRole.OPERATOR,
    reasoning_provider: "ScriptedAccessReasoner | None" = None,
) -> tuple[EmployeeAccessWorkflow, EmployeeAccessWorkflowRequest]:
    tools = ActionTools(factory, clock=lambda: NOW, id_generator=ids())
    service = EmployeeAccessWorkflow(
        factory,
        FeatureHashEmbeddingProvider(dimensions=128),
        action_tools=tools,
        reasoning_provider=reasoning_provider,
        clock=lambda: NOW,
    )
    request = EmployeeAccessWorkflowRequest(
        workflow_id=f"IT-WORKFLOW-{role.value.upper()}",
        case_id="ITCASE-2001",
        actor=Actor(actor_id=f"USER-{role.value.upper()}", role=role),
    )
    return service, request


class RecordingEmployeeAgentRuntime:
    def __init__(self, *, repository_id: str = "REPO-ML-PLATFORM") -> None:
        self.repository_id = repository_id
        self.calls: list[dict[str, object]] = []

    def run(self, **kwargs: object) -> MultiAgentReasoningResult:
        self.calls.append(kwargs)
        return MultiAgentReasoningResult.model_validate(
            {
                "workflow_id": kwargs["workflow_id"],
                "case_id": kwargs["case_id"],
                "tenant_id": kwargs["tenant_id"],
                "domain": "employee_it",
                "supervisor": {
                    "goal": "Investigate the repository access ticket.",
                    "issues": ["ACCESS-REQUEST-2001"],
                    "plan_steps": [
                        {
                            "step_id": "STEP-1",
                            "objective": "Read identity and access state.",
                            "assigned_role": "investigation",
                        }
                    ],
                    "required_evidence": ["IT access snapshot"],
                    "delegations": ["investigation", "policy", "resolution", "critic"],
                    "parallelizable_tasks": [],
                    "missing_information": [],
                    "next_agent": "investigation",
                    "stopping_condition": "The critic accepts a grounded recommendation.",
                },
                "investigation": {
                    "facts": [],
                    "evidence_ids": ["OBS-IT-1"],
                    "contradictions": [],
                    "missing_evidence": [],
                    "confidence": 0.98,
                    "source_provenance": ["employee IT snapshot"],
                    "complete": True,
                },
                "policy": {
                    "applicable_policy": "POLICY-REPOSITORY-ACCESS",
                    "citations": ["POLICY-REPOSITORY-ACCESS"],
                    "policy_versions": {"POLICY-REPOSITORY-ACCESS": 1},
                    "supporting_sections": ["Approval and eligibility"],
                    "conflicts": [],
                    "missing_policy": False,
                    "policy_interpretation": "Eligible employees may receive approved least-privilege access.",
                    "uncertainty": [],
                    "complete": True,
                },
                "resolution": {
                    "issue_resolutions": [
                        {
                            "issue_id": "ACCESS-REQUEST-2001",
                            "disposition": "access",
                            "recommendation": "Submit the approved request to deterministic access controls.",
                            "evidence_ids": ["OBS-IT-1"],
                            "policy_citations": ["POLICY-REPOSITORY-ACCESS"],
                        }
                    ],
                    "proposed_actions": [
                        {
                            "action_type": "grant_repository_access",
                            "issue_id": "ACCESS-REQUEST-2001",
                            "resource_id": self.repository_id,
                            "amount": None,
                            "requires_approval": True,
                        }
                    ],
                    "evidence_support": ["OBS-IT-1"],
                    "policy_support": ["POLICY-REPOSITORY-ACCESS"],
                    "risk_flags": [],
                    "uncertainty": [],
                    "escalation_needed": False,
                },
                "critic": {
                    "decision": "accept",
                    "unsupported_claims": [],
                    "missing_evidence": [],
                    "contradictions": [],
                    "unsafe_actions": [],
                    "citation_issues": [],
                    "partial_completion": [],
                    "summary": "Grounded recommendation; deterministic controls remain authoritative.",
                },
                "status": "ready_for_control_plane",
                "replan_count": 0,
                "agent_call_count": 5,
                "tool_call_count": 2,
                "usage": {
                    "agent_steps": 5,
                    "model_calls": 5,
                    "tool_calls": 2,
                    "input_tokens": 900,
                    "output_tokens": 250,
                },
                "agent_run_ids": [f"ARUN-IT-{index}" for index in range(1, 6)],
            }
        )


def test_employee_access_uses_agents_then_deterministic_controls(
    employee_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = employee_database
    agents = RecordingEmployeeAgentRuntime()
    service = EmployeeAccessWorkflow(
        factory,
        FeatureHashEmbeddingProvider(dimensions=128),
        action_tools=ActionTools(factory, clock=lambda: NOW, id_generator=ids()),
        agent_runtime=agents,
        tenant_id="TENANT-TEST",
        clock=lambda: NOW,
    )
    result = service.run(
        EmployeeAccessWorkflowRequest(
            workflow_id="IT-WORKFLOW-AGENTS",
            case_id="ITCASE-2001",
            actor=Actor(actor_id="USER-OPERATOR", role=ActorRole.OPERATOR),
        )
    )

    assert result.outcome == EmployeeWorkflowOutcome.ACCESS_VERIFIED
    assert result.execution_mode == "live_model"
    assert result.agent_assessment is not None
    assert agents.calls[0]["domain"].value == "employee_it"


def test_employee_agent_cannot_redirect_access_to_another_repository(
    employee_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = employee_database
    agents = RecordingEmployeeAgentRuntime(repository_id="REPO-OTHER")
    service = EmployeeAccessWorkflow(
        factory,
        FeatureHashEmbeddingProvider(dimensions=128),
        action_tools=ActionTools(factory, clock=lambda: NOW, id_generator=ids()),
        agent_runtime=agents,
        tenant_id="TENANT-TEST",
        clock=lambda: NOW,
    )
    result = service.run(
        EmployeeAccessWorkflowRequest(
            workflow_id="IT-WORKFLOW-MISMATCH",
            case_id="ITCASE-2001",
            actor=Actor(actor_id="USER-OPERATOR", role=ActorRole.OPERATOR),
        )
    )

    assert result.outcome == EmployeeWorkflowOutcome.NEEDS_REVIEW
    assert result.error_code == "agent_action_mismatch"
    with factory() as session:
        assert session.scalar(select(func.count(GitRepositoryAccessRecord.access_id))) == 0


class ScriptedAccessReasoner:
    provider_name = "test"
    model_name = "scripted-access-v1"

    def __init__(self, disposition: ReasoningDisposition) -> None:
        self.disposition = disposition
        self.contexts: list[ReasoningContext] = []

    def assess(self, context: ReasoningContext) -> ReasoningAssessment:
        self.contexts.append(context)
        supported = self.disposition == ReasoningDisposition.ACCESS_CANDIDATE
        return ReasoningAssessment(
            summary="Employee access evidence and policy were reviewed.",
            conclusion=(
                ReasoningConclusion.CLAIM_SUPPORTED
                if supported
                else ReasoningConclusion.EVIDENCE_INSUFFICIENT
            ),
            recommended_disposition=self.disposition,
            supporting_evidence_ids=[context.evidence[0].evidence_id],
            cited_policy_chunk_ids=[context.policy_excerpts[0].chunk_id],
            missing_information=[] if supported else ["Manual confirmation"],
            risk_notes=["Deterministic gates remain authoritative."],
            rationale="The model is advisory and does not authorize the access action.",
        )


def test_employee_access_workflow_grants_and_verifies_all_final_state(
    employee_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = employee_database
    provider = ScriptedAccessReasoner(ReasoningDisposition.ACCESS_CANDIDATE)
    service, request = workflow(factory, reasoning_provider=provider)

    result = service.run(request)

    assert result.status == WorkflowStatus.COMPLETED
    assert result.outcome == EmployeeWorkflowOutcome.ACCESS_VERIFIED
    assert result.decision == EmployeeWorkflowDecision.GRANT_ACCESS
    assert result.operation is not None and result.operation.verified
    assert result.verified_access_id == result.operation.resource_id
    assert any(item.document_id == "POLICY-REPOSITORY-ACCESS" for item in result.policy_citations)
    assert provider.contexts[0].issue_type.value == "repository_access"
    assert result.node_history == [
        "load_case",
        "inspect_eligibility",
        "inspect_access",
        "retrieve_policy",
        "reason_case",
        "decide",
        "grant_access",
        "verify_access",
        "complete",
    ]

    with factory() as session:
        snapshot = EmployeeITStore(session).get_snapshot("ITCASE-2001")
        assert snapshot.repository_access is not None
        assert snapshot.group_membership is not None
        assert snapshot.access_request.status == AccessRequestStatus.FULFILLED
        assert snapshot.access_case.status.value == "resolved"
        assert snapshot.ticket.status.value == "resolved"
        assert len(snapshot.notifications) == 1
        operation = session.scalar(
            select(OperationRecord).where(
                OperationRecord.operation_type == OperationType.GRANT_REPOSITORY_ACCESS
            )
        )
        assert operation is not None and operation.result_resource_id == result.verified_access_id
        audit_types = list(
            session.scalars(
                select(AuditEventRecord.event_type)
                .where(AuditEventRecord.operation_id == operation.operation_id)
                .order_by(AuditEventRecord.sequence_number)
            )
        )
        assert audit_types == [
            AuditEventType.REQUESTED,
            AuditEventType.AUTHORIZED,
            AuditEventType.EXECUTED,
            AuditEventType.VERIFIED,
        ]


def test_access_workflow_denies_unprivileged_agent_without_writing_access(
    employee_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = employee_database
    service, request = workflow(factory, role=ActorRole.AGENT)

    result = service.run(request)

    assert result.outcome == EmployeeWorkflowOutcome.NEEDS_REVIEW
    assert result.error_code == "permission_denied"
    with factory() as session:
        assert session.scalar(select(func.count(GitRepositoryAccessRecord.access_id))) == 0
        assert session.scalar(select(func.count(ITNotificationRecord.notification_id))) == 0


def test_repository_access_replay_returns_original_verified_result(
    employee_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = employee_database
    service, workflow_request = workflow(factory)
    first = service.run(workflow_request)
    assert first.operation is not None
    action_request = GrantRepositoryAccessRequest(
        idempotency_key="repository-access-ACCESS-REQUEST-2001",
        case_id="ITCASE-2001",
        access_request_id="ACCESS-REQUEST-2001",
        employee_id="EMP-2001",
        identity_id="IDENTITY-2001",
        repository_id="REPO-ML-PLATFORM",
        access_level=RepositoryAccessLevel.WRITE,
        reason="New ML Platform engineer requires repository access for assigned work.",
    )

    replay = service.action_tools.grant_repository_access(action_request, workflow_request.actor)

    assert replay.resource_id == first.operation.resource_id
    assert replay.idempotent_replay is True
    assert replay.verified is True
    with factory() as session:
        assert session.scalar(select(func.count(GitRepositoryAccessRecord.access_id))) == 1
        assert session.scalar(select(func.count(ITNotificationRecord.notification_id))) == 1


@pytest.mark.parametrize(
    ("mutation", "error_code"),
    [
        ("inactive_employee", "employee_inactive"),
        ("missing_mfa", "mfa_required"),
        ("missing_team", "team_membership_required"),
        ("inactive_git", "git_account_inactive"),
        ("pending_approval", "manager_approval_required"),
    ],
)
def test_access_workflow_fails_closed_for_ineligible_or_unapproved_state(
    employee_database: tuple[Engine, sessionmaker[Session]],
    mutation: str,
    error_code: str,
) -> None:
    _, factory = employee_database
    with factory.begin() as session:
        if mutation == "inactive_employee":
            employee = session.get(EmployeeRecord, "EMP-2001")
            assert employee is not None
            employee.status = EmploymentStatus.LEAVE
        elif mutation == "missing_mfa":
            identity = session.get(EnterpriseIdentityRecord, "IDENTITY-2001")
            assert identity is not None
            identity.mfa_enrolled = False
        elif mutation == "missing_team":
            membership = session.get(
                EmployeeTeamMembershipRecord,
                {"employee_id": "EMP-2001", "team_id": "TEAM-ML-PLATFORM"},
            )
            assert membership is not None
            membership.status = MembershipStatus.REVOKED
        elif mutation == "inactive_git":
            git_account = session.get(GitAccountRecord, "GIT-ACCOUNT-2001")
            assert git_account is not None
            git_account.status = GitAccountStatus.SUSPENDED
        else:
            access_request = session.get(ITAccessRequestRecord, "ACCESS-REQUEST-2001")
            assert access_request is not None
            access_request.status = AccessRequestStatus.PENDING_APPROVAL
            access_request.approved_by = None
            access_request.approved_at = None

    service, request = workflow(factory)
    result = service.run(request)

    assert result.outcome == EmployeeWorkflowOutcome.NEEDS_REVIEW
    assert result.error_code == error_code
    with factory() as session:
        assert session.scalar(select(func.count(GitRepositoryAccessRecord.access_id))) == 0


def test_partial_existing_access_is_escalated_instead_of_overwritten(
    employee_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = employee_database
    with factory.begin() as session:
        session.add(
            DirectoryGroupMembershipRecord(
                membership_id="GM-PARTIAL",
                group_id="GROUP-ML-PLATFORM-DEVELOPERS",
                identity_id="IDENTITY-2001",
                status=MembershipStatus.ACTIVE,
                granted_at=NOW,
            )
        )

    service, request = workflow(factory)
    result = service.run(request)

    assert result.outcome == EmployeeWorkflowOutcome.NEEDS_REVIEW
    assert result.error_code == "existing_access_conflict"
    direct_request = GrantRepositoryAccessRequest(
        idempotency_key="direct-partial-grant",
        case_id="ITCASE-2001",
        access_request_id="ACCESS-REQUEST-2001",
        employee_id="EMP-2001",
        identity_id="IDENTITY-2001",
        repository_id="REPO-ML-PLATFORM",
        access_level=RepositoryAccessLevel.WRITE,
        reason="The direct tool must enforce the same partial-access safety stop.",
    )
    with pytest.raises(BusinessRuleError, match="partial directory access"):
        service.action_tools.grant_repository_access(direct_request, request.actor)
    with factory() as session:
        assert session.scalar(select(func.count(GitRepositoryAccessRecord.access_id))) == 0
        assert session.scalar(select(func.count(DirectoryGroupMembershipRecord.membership_id))) == 1


def test_existing_exact_access_is_idempotent_no_action(
    employee_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = employee_database
    with factory.begin() as session:
        session.add_all(
            [
                DirectoryGroupMembershipRecord(
                    membership_id="GM-EXISTING",
                    group_id="GROUP-ML-PLATFORM-DEVELOPERS",
                    identity_id="IDENTITY-2001",
                    status=MembershipStatus.ACTIVE,
                    granted_at=NOW,
                ),
                GitRepositoryAccessRecord(
                    access_id="GITACCESS-EXISTING",
                    repository_id="REPO-ML-PLATFORM",
                    git_account_id="GIT-ACCOUNT-2001",
                    level=RepositoryAccessLevel.WRITE,
                    status=MembershipStatus.ACTIVE,
                    granted_at=NOW,
                ),
            ]
        )

    service, request = workflow(factory)
    result = service.run(request)

    assert result.outcome == EmployeeWorkflowOutcome.ALREADY_SATISFIED
    assert result.decision == EmployeeWorkflowDecision.NO_ACTION
    assert result.verified_access_id == "GITACCESS-EXISTING"
    with factory() as session:
        assert session.scalar(select(func.count(OperationRecord.operation_id))) == 0


@pytest.mark.parametrize("level", [RepositoryAccessLevel.READ, RepositoryAccessLevel.MAINTAIN])
def test_different_existing_access_level_is_not_overwritten(
    employee_database: tuple[Engine, sessionmaker[Session]], level: RepositoryAccessLevel
) -> None:
    _, factory = employee_database
    with factory.begin() as session:
        session.add(
            GitRepositoryAccessRecord(
                access_id="GITACCESS-CONFLICT",
                repository_id="REPO-ML-PLATFORM",
                git_account_id="GIT-ACCOUNT-2001",
                level=level,
                status=MembershipStatus.ACTIVE,
                granted_at=NOW,
            )
        )
    service, request = workflow(factory)
    result = service.run(request)
    assert result.error_code == "existing_access_conflict"
    with factory() as session:
        assert session.get(GitRepositoryAccessRecord, "GITACCESS-CONFLICT").level == level
        assert session.scalar(select(func.count(OperationRecord.operation_id))) == 0


def test_advisory_reasoning_cannot_override_deterministic_control(
    employee_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = employee_database
    provider = ScriptedAccessReasoner(ReasoningDisposition.MANUAL_REVIEW)
    service, request = workflow(factory, reasoning_provider=provider)

    result = service.run(request)

    assert result.outcome == EmployeeWorkflowOutcome.NEEDS_REVIEW
    assert result.error_code == "reasoning_recommends_review"
    with factory() as session:
        assert session.scalar(select(func.count(GitRepositoryAccessRecord.access_id))) == 0


def test_employee_it_evaluation_dataset_passes() -> None:
    cases = load_employee_evaluation_cases(Path("evals/workflows/employee_it.jsonl"))

    report = evaluate_employee_workflow_cases(cases)

    assert report.case_count == 14
    assert report.passed_count == 14
    assert report.failed_count == 0
