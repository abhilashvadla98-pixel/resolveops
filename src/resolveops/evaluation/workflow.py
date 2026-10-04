from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from resolveops.database.base import Base
from resolveops.database.knowledge_records import KnowledgeDocumentRecord
from resolveops.database.records import (
    CaseIssueRecord,
    PaymentRecord,
    RefundRecord,
    ReturnRecord,
)
from resolveops.database.seed import seed_all
from resolveops.database.session import create_session_factory
from resolveops.evaluation.models import (
    ActionBehavior,
    ReasoningBehavior,
    ScenarioFixture,
    WorkflowEvaluationCase,
    WorkflowEvaluationReport,
    WorkflowObservation,
)
from resolveops.evaluation.scoring import (
    build_workflow_report,
    evaluation_error_result,
    score_workflow_case,
)
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.knowledge.ingestion import ingest_directory
from resolveops.knowledge.models import KnowledgeStatus
from resolveops.models.case import CaseIssueStatus, IssueFinding
from resolveops.models.payment import PaymentStatus
from resolveops.models.refund import RefundKind, RefundStatus
from resolveops.models.returns import ReturnStatus
from resolveops.observability.sinks import TraceSink
from resolveops.operations.actions import ActionTools
from resolveops.operations.errors import TransientOperationError
from resolveops.operations.models import Actor, IssueRefundRequest, OperationResult
from resolveops.operations.reliability import ReliabilityPolicy
from resolveops.reasoning.errors import ReasoningProviderError
from resolveops.reasoning.models import (
    ReasoningAssessment,
    ReasoningConclusion,
    ReasoningContext,
    ReasoningDisposition,
)
from resolveops.workflows.customer_issue import CustomerIssueWorkflow
from resolveops.workflows.models import WorkflowRequest, WorkflowResult

DEFAULT_WORKFLOW_DATASET_NAME = "customer-operations-workflow-v2"
DEFAULT_POLICY_DIRECTORY = Path("domain_packs/customer_operations/policies")
EVALUATION_TIME = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


class EvaluationReasoningProvider:
    provider_name = "evaluation-script"
    model_name = "ground-truth-v1"

    def __init__(self, behavior: ReasoningBehavior) -> None:
        self.behavior = behavior

    def assess(self, context: ReasoningContext) -> ReasoningAssessment:
        if self.behavior == ReasoningBehavior.PROVIDER_FAILURE:
            raise ReasoningProviderError(
                "reasoning_provider_failed",
                "The evaluation reasoning provider failed as configured.",
            )
        evidence_id = (
            "E-UNKNOWN"
            if self.behavior == ReasoningBehavior.INVALID_REFERENCE
            else context.evidence[0].evidence_id
        )
        chunk_id = (
            "CHUNK-UNKNOWN"
            if self.behavior == ReasoningBehavior.INVALID_REFERENCE
            else context.policy_excerpts[0].chunk_id
        )
        conclusion = ReasoningConclusion.CLAIM_SUPPORTED
        disposition = ReasoningDisposition.REFUND_CANDIDATE
        if self.behavior == ReasoningBehavior.MANUAL_REVIEW:
            conclusion = ReasoningConclusion.EVIDENCE_INSUFFICIENT
            disposition = ReasoningDisposition.MANUAL_REVIEW
        elif self.behavior == ReasoningBehavior.REJECT_CLAIM:
            conclusion = ReasoningConclusion.CLAIM_NOT_SUPPORTED
            disposition = ReasoningDisposition.REJECT_CLAIM
        return ReasoningAssessment(
            summary="The supplied operational evidence and active policy were evaluated.",
            conclusion=conclusion,
            recommended_disposition=disposition,
            supporting_evidence_ids=[evidence_id],
            cited_policy_chunk_ids=[chunk_id],
            missing_information=[],
            risk_notes=["Deterministic controls still decide whether an action is permitted."],
            rationale="The assessment is advisory and grounded in the supplied references.",
        )


class TimeoutRefundTools(ActionTools):
    def _execute_refund(
        self, session: Session, refund_id: str, request: IssueRefundRequest
    ) -> None:
        raise TransientOperationError(
            "provider_timeout", "The refund provider timed out before confirming the action."
        )


class DisappearingRefundTools(ActionTools):
    def issue_refund(self, request: IssueRefundRequest, actor: Actor) -> OperationResult:
        result = super().issue_refund(request, actor)
        with self.session_factory.begin() as session:
            refund = session.get(RefundRecord, result.resource_id)
            if refund is not None:
                session.delete(refund)
        return result


class FailedVerificationRefundTools(ActionTools):
    @staticmethod
    def _verify_refund(session: Session, refund_id: str, request: IssueRefundRequest) -> bool:
        return False


def evaluate_workflow_cases(
    cases: Sequence[WorkflowEvaluationCase],
    *,
    dataset_name: str = DEFAULT_WORKFLOW_DATASET_NAME,
    policy_directory: Path = DEFAULT_POLICY_DIRECTORY,
    observability_sink: TraceSink | None = None,
) -> WorkflowEvaluationReport:
    if not cases:
        raise ValueError("workflow evaluation requires at least one case")
    results = []
    for evaluation_case in cases:
        engine = _evaluation_engine()
        try:
            observation = _run_case(
                engine,
                evaluation_case,
                policy_directory,
                observability_sink=observability_sink,
            )
            results.append(score_workflow_case(evaluation_case, observation))
        except Exception as exc:  # noqa: BLE001 - one broken case must not hide later results
            results.append(evaluation_error_result(evaluation_case, exc))
        finally:
            engine.dispose()
    return build_workflow_report(dataset_name, results)


def _run_case(
    engine: Engine,
    evaluation_case: WorkflowEvaluationCase,
    policy_directory: Path,
    *,
    observability_sink: TraceSink | None = None,
) -> WorkflowObservation:
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    embedding_provider = FeatureHashEmbeddingProvider(dimensions=128)
    with factory.begin() as session:
        seed_all(session)
        ingest_directory(
            session,
            policy_directory,
            embedding_provider,
            ingested_at=EVALUATION_TIME,
        )
    _apply_fixture(factory, evaluation_case)
    before_count = _refund_count(factory, evaluation_case.issue_id)
    action_tools = _action_tools(
        factory,
        evaluation_case,
        observability_sink=observability_sink,
    )
    reasoning_provider = (
        None
        if evaluation_case.reasoning_behavior == ReasoningBehavior.NONE
        else EvaluationReasoningProvider(evaluation_case.reasoning_behavior)
    )
    request = WorkflowRequest(
        workflow_id=f"WORKFLOW-{evaluation_case.evaluation_id}",
        case_id="CASE-1001",
        issue_id=evaluation_case.issue_id,
        actor=Actor(
            actor_id=f"EVAL-{evaluation_case.actor_role.value.upper()}",
            role=evaluation_case.actor_role,
        ),
        refund_request=_refund_request(evaluation_case),
    )
    result = CustomerIssueWorkflow(
        factory,
        embedding_provider,
        action_tools=action_tools,
        reasoning_provider=reasoning_provider,
        observability_sink=observability_sink,
        clock=lambda: EVALUATION_TIME,
    ).run(request)
    with factory() as session:
        issue = session.get(CaseIssueRecord, evaluation_case.issue_id)
        refund = (
            session.get(RefundRecord, result.verified_resource_id)
            if result.verified_resource_id is not None
            else None
        )
        return _observe_result(
            result,
            new_refund_created=_refund_count(factory, evaluation_case.issue_id) > before_count,
            issue_status=issue.status if issue else None,
            refund_status=refund.status if refund else None,
        )


def _evaluation_engine() -> Engine:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _apply_fixture(factory: sessionmaker[Session], evaluation_case: WorkflowEvaluationCase) -> None:
    fixture = evaluation_case.fixture
    with factory.begin() as session:
        if fixture in {
            ScenarioFixture.DUPLICATE_ACTIONABLE,
            ScenarioFixture.DUPLICATE_SECOND_PAYMENT_PENDING,
            ScenarioFixture.DUPLICATE_EXISTING_REFUND,
        }:
            _make_issue_actionable(session, "ISSUE-1001")
        elif fixture in {
            ScenarioFixture.RETURN_ACTIONABLE,
            ScenarioFixture.RETURN_NOT_RECEIVED,
        }:
            _make_return_actionable(session)
        elif fixture == ScenarioFixture.REQUIRED_POLICY_MISSING:
            if evaluation_case.issue_id == "ISSUE-1001":
                _make_issue_actionable(session, "ISSUE-1001")
                required_document = "POLICY-DUPLICATE-CHARGE"
            else:
                _make_return_actionable(session)
                required_document = "POLICY-RETURN-REFUND"
            documents = session.scalars(
                select(KnowledgeDocumentRecord).where(
                    KnowledgeDocumentRecord.document_id == required_document
                )
            )
            for document in documents:
                document.status = KnowledgeStatus.SUPERSEDED

        if fixture in {
            ScenarioFixture.DUPLICATE_OBLIGATION_MISSING,
            ScenarioFixture.DUPLICATE_OBLIGATION_CONFLICT,
        }:
            payment = session.get(PaymentRecord, "PAY-1002")
            if payment is None:
                raise RuntimeError("evaluation seed payment is missing")
            if fixture == ScenarioFixture.DUPLICATE_OBLIGATION_MISSING:
                payment.obligation_id = None
                payment.obligation_amount = None
            else:
                payment.obligation_id = "OBLIGATION-CONFLICTING"
        elif fixture == ScenarioFixture.DUPLICATE_SECOND_PAYMENT_PENDING:
            payment = session.get(PaymentRecord, "PAY-1002")
            if payment is None:
                raise RuntimeError("evaluation seed payment is missing")
            payment.status = PaymentStatus.AUTHORIZED
            payment.captured_at = None
        elif fixture == ScenarioFixture.DUPLICATE_EXISTING_REFUND:
            session.add(
                RefundRecord(
                    refund_id="REF-EVAL-EXISTING",
                    payment_id="PAY-1002",
                    order_id="ORD-48391",
                    issue_id="ISSUE-1001",
                    return_id=None,
                    amount=Decimal("1499.00"),
                    currency="USD",
                    status=RefundStatus.PROCESSING,
                    kind=RefundKind.DUPLICATE_CHARGE,
                    reason="Existing provider refund found during evaluation",
                    created_at=EVALUATION_TIME,
                    completed_at=None,
                )
            )
        elif fixture == ScenarioFixture.RETURN_NOT_RECEIVED:
            customer_return = session.get(ReturnRecord, "RET-3001")
            if customer_return is None:
                raise RuntimeError("evaluation seed return is missing")
            customer_return.status = ReturnStatus.IN_TRANSIT
            customer_return.received_at = None
        elif fixture == ScenarioFixture.RETURN_UNLINKED:
            issue = session.get(CaseIssueRecord, "ISSUE-1002")
            if issue is None:
                raise RuntimeError("evaluation seed issue is missing")
            issue.return_id = None


def _make_issue_actionable(session: Session, issue_id: str) -> None:
    issue = session.get(CaseIssueRecord, issue_id)
    if issue is None:
        raise RuntimeError("evaluation seed issue is missing")
    issue.finding = IssueFinding.CONFIRMED
    issue.status = CaseIssueStatus.ACTION_PENDING


def _make_return_actionable(session: Session) -> None:
    _make_issue_actionable(session, "ISSUE-1002")
    refund = session.get(RefundRecord, "REF-2001")
    if refund is None:
        raise RuntimeError("evaluation seed refund is missing")
    refund.status = RefundStatus.FAILED
    refund.completed_at = None


def _action_tools(
    factory: sessionmaker[Session],
    evaluation_case: WorkflowEvaluationCase,
    *,
    observability_sink: TraceSink | None = None,
) -> ActionTools:
    sequence = iter(range(1, 100))
    identifiers: Callable[[str], str] = lambda prefix: (
        f"{prefix}-{evaluation_case.evaluation_id}-{next(sequence):04d}"
    )
    tools: type[ActionTools] = {
        ActionBehavior.NORMAL: ActionTools,
        ActionBehavior.TIMEOUT: TimeoutRefundTools,
        ActionBehavior.DISAPPEARING_RESOURCE: DisappearingRefundTools,
        ActionBehavior.FAILED_VERIFICATION: FailedVerificationRefundTools,
    }[evaluation_case.action_behavior]
    return tools(
        factory,
        clock=lambda: EVALUATION_TIME,
        id_generator=identifiers,
        reliability_policy=ReliabilityPolicy(
            max_attempts=2,
            initial_backoff_seconds=0,
        ),
        sleeper=lambda _: None,
        observability_sink=observability_sink,
    )


def _refund_request(evaluation_case: WorkflowEvaluationCase) -> IssueRefundRequest | None:
    proposal = evaluation_case.refund_proposal
    if proposal is None:
        return None
    return IssueRefundRequest(
        idempotency_key=f"refund-{evaluation_case.evaluation_id.lower()}",
        case_id="CASE-1001",
        issue_id=evaluation_case.issue_id,
        payment_id=proposal.payment_id,
        amount=proposal.amount,
        currency=proposal.currency,
        kind=proposal.kind,
        reason=proposal.reason,
        return_id=proposal.return_id,
    )


def _refund_count(factory: sessionmaker[Session], issue_id: str) -> int:
    with factory() as session:
        return (
            session.scalar(
                select(func.count())
                .select_from(RefundRecord)
                .where(RefundRecord.issue_id == issue_id)
            )
            or 0
        )


def _observe_result(
    result: WorkflowResult,
    *,
    new_refund_created: bool,
    issue_status: CaseIssueStatus | None = None,
    refund_status: RefundStatus | None = None,
) -> WorkflowObservation:
    policy_document_ids = list(dict.fromkeys(item.document_id for item in result.policy_citations))
    reasoning_grounded: bool | None = None
    if result.reasoning is not None:
        evidence_ids = {f"E{index}" for index in range(1, len(result.evidence) + 1)}
        chunk_ids = {item.chunk_id for item in result.policy_citations}
        reasoning_grounded = (
            set(result.reasoning.assessment.supporting_evidence_ids) <= evidence_ids
            and set(result.reasoning.assessment.cited_policy_chunk_ids) <= chunk_ids
        )
    return WorkflowObservation(
        outcome=result.outcome,
        status=result.status,
        issue_status=issue_status,
        refund_status=refund_status,
        decision=result.decision,
        error_code=result.error_code,
        new_refund_created=new_refund_created,
        verified=bool(
            result.operation is not None
            and result.operation.verified
            and result.verified_resource_id == result.operation.resource_id
        ),
        node_history=result.node_history,
        policy_document_ids=policy_document_ids,
        reasoning_grounded=reasoning_grounded,
    )
