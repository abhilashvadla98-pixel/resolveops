from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from resolveops.database.base import Base
from resolveops.database.employee_it_records import (
    DirectoryGroupMembershipRecord,
    EmployeeRecord,
    EmployeeTeamMembershipRecord,
    EnterpriseIdentityRecord,
    GitAccountRecord,
    GitRepositoryAccessRecord,
    ITAccessRequestRecord,
)
from resolveops.database.knowledge_records import KnowledgeDocumentRecord
from resolveops.database.seed import seed_all
from resolveops.database.session import create_session_factory
from resolveops.employee_it.models import (
    AccessRequestStatus,
    EmploymentStatus,
    GitAccountStatus,
    IdentityStatus,
    MembershipStatus,
    RepositoryAccessLevel,
)
from resolveops.employee_it.workflow import EmployeeAccessWorkflow
from resolveops.employee_it.workflow_models import EmployeeAccessWorkflowRequest
from resolveops.evaluation.employee_models import (
    EmployeeCategoryMetrics,
    EmployeeEvaluationReport,
    EmployeeEvaluationResult,
    EmployeeReasoningBehavior,
    EmployeeScenarioFixture,
    EmployeeWorkflowEvaluationCase,
    EmployeeWorkflowObservation,
)
from resolveops.evaluation.models import EvaluationAssertion
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.knowledge.ingestion import ingest_directory
from resolveops.knowledge.models import KnowledgeStatus
from resolveops.operations.models import Actor, OperationStatus
from resolveops.reasoning.models import (
    ReasoningAssessment,
    ReasoningConclusion,
    ReasoningContext,
    ReasoningDisposition,
)

DEFAULT_EMPLOYEE_DATASET_NAME = "employee-it-access-workflow-v1"
DEFAULT_EMPLOYEE_POLICY_DIRECTORY = Path("domain_packs/employee_it/policies")
EVALUATION_TIME = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


class EmployeeEvaluationReasoner:
    provider_name = "evaluation-script"
    model_name = "employee-access-ground-truth-v1"

    def __init__(self, behavior: EmployeeReasoningBehavior) -> None:
        self.behavior = behavior

    def assess(self, context: ReasoningContext) -> ReasoningAssessment:
        supported = self.behavior == EmployeeReasoningBehavior.SUPPORT_ACCESS
        return ReasoningAssessment(
            summary="Employee access evidence and active policy were evaluated.",
            conclusion=(
                ReasoningConclusion.CLAIM_SUPPORTED
                if supported
                else ReasoningConclusion.EVIDENCE_INSUFFICIENT
            ),
            recommended_disposition=(
                ReasoningDisposition.ACCESS_CANDIDATE
                if supported
                else ReasoningDisposition.MANUAL_REVIEW
            ),
            supporting_evidence_ids=[context.evidence[0].evidence_id],
            cited_policy_chunk_ids=[context.policy_excerpts[0].chunk_id],
            missing_information=[] if supported else ["Manual review requested"],
            risk_notes=["Deterministic controls remain authoritative."],
            rationale="The scripted recommendation is advisory.",
        )


def evaluate_employee_workflow_cases(
    cases: Sequence[EmployeeWorkflowEvaluationCase],
    *,
    dataset_name: str = DEFAULT_EMPLOYEE_DATASET_NAME,
    policy_directory: Path = DEFAULT_EMPLOYEE_POLICY_DIRECTORY,
) -> EmployeeEvaluationReport:
    if not cases:
        raise ValueError("employee workflow evaluation requires at least one case")
    results: list[EmployeeEvaluationResult] = []
    for evaluation_case in cases:
        engine = _evaluation_engine()
        try:
            observation = _run_case(engine, evaluation_case, policy_directory)
            results.append(_score(evaluation_case, observation))
        except Exception as exc:  # noqa: BLE001 - retain all case results
            results.append(
                EmployeeEvaluationResult(
                    evaluation_id=evaluation_case.evaluation_id,
                    title=evaluation_case.title,
                    category=evaluation_case.category,
                    passed=False,
                    assertions=[
                        EvaluationAssertion(
                            name="execution",
                            expected="completed without exception",
                            actual=type(exc).__name__,
                            passed=False,
                        )
                    ],
                    execution_error=f"{type(exc).__name__}: {exc}",
                )
            )
        finally:
            engine.dispose()
    category_metrics = []
    for category in sorted({item.category for item in results}, key=lambda item: item.value):
        category_results = [item for item in results if item.category == category]
        passed = sum(item.passed for item in category_results)
        category_metrics.append(
            EmployeeCategoryMetrics(
                category=category,
                case_count=len(category_results),
                passed_count=passed,
                pass_rate=passed / len(category_results),
            )
        )
    passed_count = sum(item.passed for item in results)
    return EmployeeEvaluationReport(
        dataset_name=dataset_name,
        case_count=len(results),
        passed_count=passed_count,
        failed_count=len(results) - passed_count,
        pass_rate=passed_count / len(results),
        category_metrics=category_metrics,
        cases=results,
    )


def _evaluation_engine() -> Engine:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _run_case(
    engine: Engine,
    evaluation_case: EmployeeWorkflowEvaluationCase,
    policy_directory: Path,
) -> EmployeeWorkflowObservation:
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    provider = FeatureHashEmbeddingProvider(dimensions=128)
    with factory.begin() as session:
        seed_all(session)
        ingest_directory(session, policy_directory, provider, ingested_at=EVALUATION_TIME)
    _apply_fixture(factory, evaluation_case.fixture)
    before = _access_count(factory)
    reasoner = (
        None
        if evaluation_case.reasoning_behavior == EmployeeReasoningBehavior.NONE
        else EmployeeEvaluationReasoner(evaluation_case.reasoning_behavior)
    )
    result = EmployeeAccessWorkflow(
        factory,
        provider,
        reasoning_provider=reasoner,
        clock=lambda: EVALUATION_TIME,
    ).run(
        EmployeeAccessWorkflowRequest(
            workflow_id=f"WORKFLOW-{evaluation_case.evaluation_id}",
            case_id="ITCASE-2001",
            actor=Actor(
                actor_id=f"EVAL-{evaluation_case.actor_role.value.upper()}",
                role=evaluation_case.actor_role,
            ),
        )
    )
    operation = result.operation
    return EmployeeWorkflowObservation(
        outcome=result.outcome,
        decision=result.decision,
        error_code=result.error_code,
        access_created=_access_count(factory) > before,
        verified=bool(
            operation and operation.status == OperationStatus.COMPLETED and operation.verified
        ),
        policy_document_ids=sorted({item.document_id for item in result.policy_citations}),
    )


def _apply_fixture(factory: sessionmaker[Session], fixture: EmployeeScenarioFixture) -> None:
    with factory.begin() as session:
        if fixture == EmployeeScenarioFixture.INACTIVE_EMPLOYEE:
            employee = _required(session, EmployeeRecord, "EMP-2001")
            employee.status = EmploymentStatus.LEAVE
        elif fixture == EmployeeScenarioFixture.INACTIVE_IDENTITY:
            identity = _required(session, EnterpriseIdentityRecord, "IDENTITY-2001")
            identity.status = IdentityStatus.SUSPENDED
        elif fixture == EmployeeScenarioFixture.MISSING_MFA:
            identity_without_mfa = _required(session, EnterpriseIdentityRecord, "IDENTITY-2001")
            identity_without_mfa.mfa_enrolled = False
        elif fixture == EmployeeScenarioFixture.MISSING_TEAM:
            membership = session.get(
                EmployeeTeamMembershipRecord,
                {"employee_id": "EMP-2001", "team_id": "TEAM-ML-PLATFORM"},
            )
            if membership is None:
                raise RuntimeError("seed team membership is missing")
            membership.status = MembershipStatus.REVOKED
        elif fixture == EmployeeScenarioFixture.INACTIVE_GIT:
            git_account = _required(session, GitAccountRecord, "GIT-ACCOUNT-2001")
            git_account.status = GitAccountStatus.SUSPENDED
        elif fixture == EmployeeScenarioFixture.PENDING_APPROVAL:
            pending_request = _required(session, ITAccessRequestRecord, "ACCESS-REQUEST-2001")
            pending_request.status = AccessRequestStatus.PENDING_APPROVAL
            pending_request.approved_by = None
            pending_request.approved_at = None
        elif fixture == EmployeeScenarioFixture.WRONG_APPROVER:
            wrongly_approved = _required(session, ITAccessRequestRecord, "ACCESS-REQUEST-2001")
            wrongly_approved.approved_by = "EMP-2001"
        elif fixture == EmployeeScenarioFixture.PARTIAL_ACCESS:
            session.add(_group_membership("GM-EVAL-PARTIAL"))
        elif fixture == EmployeeScenarioFixture.EXISTING_ACCESS:
            session.add_all(
                [
                    _group_membership("GM-EVAL-EXISTING"),
                    GitRepositoryAccessRecord(
                        access_id="GITACCESS-EVAL-EXISTING",
                        repository_id="REPO-ML-PLATFORM",
                        git_account_id="GIT-ACCOUNT-2001",
                        level=RepositoryAccessLevel.WRITE,
                        status=MembershipStatus.ACTIVE,
                        granted_at=EVALUATION_TIME,
                    ),
                ]
            )
        elif fixture == EmployeeScenarioFixture.REQUIRED_POLICY_MISSING:
            documents = session.scalars(
                select(KnowledgeDocumentRecord).where(
                    KnowledgeDocumentRecord.document_id == "POLICY-REPOSITORY-ACCESS"
                )
            )
            for document in documents:
                document.status = KnowledgeStatus.SUPERSEDED


def _required[RecordT](session: Session, record_type: type[RecordT], key: str) -> RecordT:
    record = session.get(record_type, key)
    if record is None:
        raise RuntimeError(f"evaluation seed record {key} is missing")
    return record


def _group_membership(membership_id: str) -> DirectoryGroupMembershipRecord:
    return DirectoryGroupMembershipRecord(
        membership_id=membership_id,
        group_id="GROUP-ML-PLATFORM-DEVELOPERS",
        identity_id="IDENTITY-2001",
        status=MembershipStatus.ACTIVE,
        granted_at=EVALUATION_TIME,
    )


def _access_count(factory: sessionmaker[Session]) -> int:
    with factory() as session:
        return session.scalar(select(func.count(GitRepositoryAccessRecord.access_id))) or 0


def _score(
    evaluation_case: EmployeeWorkflowEvaluationCase,
    observation: EmployeeWorkflowObservation,
) -> EmployeeEvaluationResult:
    expected = evaluation_case.expected
    values = (
        ("outcome", expected.outcome.value, observation.outcome.value),
        ("decision", expected.decision.value, observation.decision.value),
        ("error_code", str(expected.error_code), str(observation.error_code)),
        ("access_created", str(expected.access_created), str(observation.access_created)),
        ("verified", str(expected.verified), str(observation.verified)),
    )
    assertions = [
        EvaluationAssertion(name=name, expected=wanted, actual=actual, passed=wanted == actual)
        for name, wanted, actual in values
    ]
    if expected.required_policy_document_id is not None:
        document_id = expected.required_policy_document_id
        assertions.append(
            EvaluationAssertion(
                name="required_policy",
                expected=document_id,
                actual=", ".join(observation.policy_document_ids),
                passed=document_id in observation.policy_document_ids,
            )
        )
    return EmployeeEvaluationResult(
        evaluation_id=evaluation_case.evaluation_id,
        title=evaluation_case.title,
        category=evaluation_case.category,
        passed=all(item.passed for item in assertions),
        assertions=assertions,
        observation=observation,
    )
