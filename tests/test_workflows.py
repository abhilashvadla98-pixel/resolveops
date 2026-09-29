from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from resolveops.database.base import Base
from resolveops.database.records import CaseIssueRecord, RefundRecord
from resolveops.database.seed import seed_all
from resolveops.database.session import create_session_factory
from resolveops.database.workflow_records import WorkflowApprovalRecord
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.knowledge.ingestion import ingest_directory
from resolveops.models.case import CaseIssueStatus, IssueFinding
from resolveops.models.refund import RefundKind
from resolveops.operations.actions import ActionTools
from resolveops.operations.models import Actor, ActorRole, IssueRefundRequest, OperationResult
from resolveops.operations.reliability import ReliabilityPolicy
from resolveops.reasoning.errors import ReasoningProviderError
from resolveops.reasoning.models import (
    ReasoningAssessment,
    ReasoningConclusion,
    ReasoningContext,
    ReasoningDisposition,
)
from resolveops.reasoning.providers import ReasoningProvider
from resolveops.workflows.customer_issue import CustomerIssueWorkflow
from resolveops.workflows.lifecycle import ApprovalDecisionError, WorkflowLifecycleStore
from resolveops.workflows.models import (
    ApprovalDecisionType,
    ApprovalStatus,
    WorkflowApprovalDecision,
    WorkflowDecision,
    WorkflowEventType,
    WorkflowLifecycleStatus,
    WorkflowOutcome,
    WorkflowPause,
    WorkflowRequest,
    WorkflowStatus,
)

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
POLICY_DIRECTORY = Path("domain_packs/customer_operations/policies")


@pytest.fixture
def workflow_database() -> tuple[Engine, sessionmaker[Session]]:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    provider = FeatureHashEmbeddingProvider(dimensions=128)
    with factory.begin() as session:
        seed_all(session)
        ingest_directory(session, POLICY_DIRECTORY, provider, ingested_at=NOW)
    yield engine, factory
    engine.dispose()


def actor(role: ActorRole = ActorRole.APPROVER) -> Actor:
    return Actor(actor_id=f"USER-{role.value.upper()}", role=role)


def refund_request(*, key: str = "workflow-refund-1") -> IssueRefundRequest:
    return IssueRefundRequest(
        idempotency_key=key,
        case_id="CASE-1001",
        issue_id="ISSUE-1001",
        payment_id="PAY-1002",
        amount=Decimal("1499.00"),
        currency="USD",
        kind=RefundKind.DUPLICATE_CHARGE,
        reason="Confirmed duplicate charge",
    )


def request(
    *,
    issue_id: str = "ISSUE-1001",
    role: ActorRole = ActorRole.APPROVER,
    proposed_refund: IssueRefundRequest | None = None,
) -> WorkflowRequest:
    return WorkflowRequest(
        workflow_id=f"WORKFLOW-{issue_id}",
        case_id="CASE-1001",
        issue_id=issue_id,
        actor=actor(role),
        refund_request=proposed_refund,
    )


def ids() -> Callable[[str], str]:
    sequence = iter(range(1, 100))
    return lambda prefix: f"{prefix}-WF-{next(sequence):04d}"


def workflow(
    factory: sessionmaker[Session],
    *,
    action_tools: ActionTools | None = None,
    reasoning_provider: ReasoningProvider | None = None,
) -> CustomerIssueWorkflow:
    return CustomerIssueWorkflow(
        factory,
        FeatureHashEmbeddingProvider(dimensions=128),
        action_tools=action_tools,
        reasoning_provider=reasoning_provider,
        clock=lambda: NOW,
    )


def durable_workflow(
    factory: sessionmaker[Session],
    checkpointer: InMemorySaver,
    lifecycle: WorkflowLifecycleStore,
    *,
    action_tools: ActionTools | None = None,
) -> CustomerIssueWorkflow:
    return CustomerIssueWorkflow(
        factory,
        FeatureHashEmbeddingProvider(dimensions=128),
        action_tools=action_tools,
        checkpointer=checkpointer,
        lifecycle_store=lifecycle,
        clock=lambda: NOW,
    )


class ScriptedReasoningProvider:
    provider_name = "test"
    model_name = "scripted-reasoner-v1"

    def __init__(
        self,
        disposition: ReasoningDisposition,
        *,
        invalid_reference: bool = False,
        fail: bool = False,
    ) -> None:
        self.disposition = disposition
        self.invalid_reference = invalid_reference
        self.fail = fail
        self.contexts: list[ReasoningContext] = []

    def assess(self, context: ReasoningContext) -> ReasoningAssessment:
        self.contexts.append(context)
        if self.fail:
            raise ReasoningProviderError(
                "reasoning_provider_failed", "The reasoning provider request failed."
            )
        evidence_id = "E999" if self.invalid_reference else context.evidence[0].evidence_id
        chunk_id = (
            "CHUNK-UNKNOWN" if self.invalid_reference else context.policy_excerpts[0].chunk_id
        )
        conclusion = (
            ReasoningConclusion.CLAIM_SUPPORTED
            if self.disposition == ReasoningDisposition.REFUND_CANDIDATE
            else ReasoningConclusion.EVIDENCE_INSUFFICIENT
        )
        return ReasoningAssessment(
            summary="Evidence and policy were reviewed for this issue.",
            conclusion=conclusion,
            recommended_disposition=self.disposition,
            supporting_evidence_ids=[evidence_id],
            cited_policy_chunk_ids=[chunk_id],
            missing_information=[],
            risk_notes=["Deterministic authorization remains required."],
            rationale="The recommendation is advisory and does not authorize an action.",
        )


def make_duplicate_issue_actionable(factory: sessionmaker[Session]) -> None:
    with factory.begin() as session:
        issue = session.get(CaseIssueRecord, "ISSUE-1001")
        assert issue is not None
        issue.finding = IssueFinding.CONFIRMED
        issue.status = CaseIssueStatus.ACTION_PENDING


def test_unconfirmed_issue_routes_to_review_without_action(
    workflow_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = workflow_database

    result = workflow(factory).run(request(proposed_refund=refund_request()))

    assert result.status == WorkflowStatus.ESCALATED
    assert result.outcome == WorkflowOutcome.NEEDS_REVIEW
    assert result.decision == WorkflowDecision.ESCALATE
    assert result.error_code == "investigation_not_confirmed"
    assert result.node_history == [
        "load_case",
        "investigate_duplicate",
        "retrieve_policy",
        "reason_case",
        "decide",
        "escalate",
    ]
    with factory() as session:
        count = session.scalar(
            select(func.count())
            .select_from(RefundRecord)
            .where(RefundRecord.issue_id == "ISSUE-1001")
        )
        assert count == 0


def test_existing_return_refund_routes_to_wait_without_duplicate_action(
    workflow_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = workflow_database

    result = workflow(factory).run(request(issue_id="ISSUE-1002"))

    assert result.status == WorkflowStatus.WAITING_EXTERNAL
    assert result.outcome == WorkflowOutcome.WAITING_EXTERNAL
    assert result.decision == WorkflowDecision.MONITOR_EXISTING_REFUND
    assert "REF-2001" in result.resolution_summary
    assert result.node_history[-1] == "wait_external"


def test_authorized_refund_executes_and_is_independently_verified(
    workflow_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = workflow_database
    make_duplicate_issue_actionable(factory)
    tools = ActionTools(factory, clock=lambda: NOW, id_generator=ids())
    provider = ScriptedReasoningProvider(ReasoningDisposition.REFUND_CANDIDATE)

    result = workflow(factory, action_tools=tools, reasoning_provider=provider).run(
        request(proposed_refund=refund_request())
    )

    assert result.status == WorkflowStatus.COMPLETED
    assert result.outcome == WorkflowOutcome.ACTION_VERIFIED
    assert result.operation is not None
    assert result.reasoning is not None
    assert result.operation.verified is True
    assert result.verified_resource_id == result.operation.resource_id
    assert any(item.document_id == "POLICY-DUPLICATE-CHARGE" for item in result.policy_citations)
    assert result.node_history[-3:] == ["execute_refund", "verify_action", "complete"]
    assert "case remains open" in result.resolution_summary


def test_approval_failure_routes_to_review(
    workflow_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = workflow_database
    make_duplicate_issue_actionable(factory)
    tools = ActionTools(factory, clock=lambda: NOW, id_generator=ids())

    result = workflow(factory, action_tools=tools).run(
        request(role=ActorRole.OPERATOR, proposed_refund=refund_request())
    )

    assert result.status == WorkflowStatus.ESCALATED
    assert result.outcome == WorkflowOutcome.NEEDS_REVIEW
    assert result.error_code == "refund_approval_required"
    assert result.operation is None


def test_workflow_fresh_read_catches_missing_action_resource(
    workflow_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = workflow_database
    make_duplicate_issue_actionable(factory)

    class DisappearingRefundTools(ActionTools):
        def issue_refund(
            self, action_request: IssueRefundRequest, action_actor: Actor
        ) -> OperationResult:
            result = super().issue_refund(action_request, action_actor)
            with self.session_factory.begin() as session:
                refund = session.get(RefundRecord, result.resource_id)
                assert refund is not None
                session.delete(refund)
            return result

    tools = DisappearingRefundTools(factory, clock=lambda: NOW, id_generator=ids())

    result = workflow(factory, action_tools=tools).run(request(proposed_refund=refund_request()))

    assert result.status == WorkflowStatus.ESCALATED
    assert result.outcome == WorkflowOutcome.NEEDS_REVIEW
    assert result.error_code == "workflow_verification_failed"
    assert result.verified_resource_id is None


def test_workflow_replans_to_monitor_after_partial_verification_failure(
    workflow_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = workflow_database
    make_duplicate_issue_actionable(factory)

    class DelayedVisibilityRefundTools(ActionTools):
        @staticmethod
        def _verify_refund(session: Session, refund_id: str, request: IssueRefundRequest) -> bool:
            return False

    tools = DelayedVisibilityRefundTools(
        factory,
        clock=lambda: NOW,
        id_generator=ids(),
        reliability_policy=ReliabilityPolicy(
            max_attempts=2,
            initial_backoff_seconds=0,
        ),
        sleeper=lambda _: None,
    )

    result = workflow(factory, action_tools=tools).run(
        request(proposed_refund=refund_request(key="workflow-partial-failure"))
    )

    assert result.status == WorkflowStatus.WAITING_EXTERNAL
    assert result.outcome == WorkflowOutcome.WAITING_EXTERNAL
    assert result.decision == WorkflowDecision.MONITOR_EXISTING_REFUND
    assert result.operation is None
    assert "replan_after_partial_failure" in result.node_history
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(RefundRecord)
                .where(RefundRecord.issue_id == "ISSUE-1001")
            )
            == 1
        )


def test_model_refund_recommendation_cannot_bypass_persisted_issue_gate(
    workflow_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = workflow_database
    provider = ScriptedReasoningProvider(ReasoningDisposition.REFUND_CANDIDATE)

    result = workflow(factory, reasoning_provider=provider).run(
        request(proposed_refund=refund_request())
    )

    assert result.reasoning is not None
    assert result.reasoning.assessment.recommended_disposition == (
        ReasoningDisposition.REFUND_CANDIDATE
    )
    assert result.error_code == "investigation_not_confirmed"
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(RefundRecord)
                .where(RefundRecord.issue_id == "ISSUE-1001")
            )
            == 0
        )


def test_reasoning_review_recommendation_stops_confirmed_refund(
    workflow_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = workflow_database
    make_duplicate_issue_actionable(factory)
    provider = ScriptedReasoningProvider(ReasoningDisposition.MANUAL_REVIEW)

    result = workflow(factory, reasoning_provider=provider).run(
        request(proposed_refund=refund_request())
    )

    assert result.status == WorkflowStatus.ESCALATED
    assert result.error_code == "reasoning_recommends_review"
    assert result.operation is None


@pytest.mark.parametrize("invalid_reference", [True, False])
def test_reasoning_failure_is_explicit_and_fails_closed(
    workflow_database: tuple[Engine, sessionmaker[Session]],
    invalid_reference: bool,
) -> None:
    _, factory = workflow_database
    make_duplicate_issue_actionable(factory)
    provider = ScriptedReasoningProvider(
        ReasoningDisposition.REFUND_CANDIDATE,
        invalid_reference=invalid_reference,
        fail=not invalid_reference,
    )

    result = workflow(factory, reasoning_provider=provider).run(
        request(proposed_refund=refund_request())
    )

    assert result.status == WorkflowStatus.ESCALATED
    assert result.error_code == (
        "unsupported_reasoning_reference" if invalid_reference else "reasoning_provider_failed"
    )
    assert result.operation is None


def test_durable_workflow_pauses_and_resumes_after_service_restart(
    workflow_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = workflow_database
    make_duplicate_issue_actionable(factory)
    checkpointer = InMemorySaver()
    event_ids = ids()
    lifecycle = WorkflowLifecycleStore(
        factory,
        clock=lambda: NOW,
        id_generator=event_ids,
    )
    tools = ActionTools(factory, clock=lambda: NOW, id_generator=ids())
    initial_request = request(
        role=ActorRole.OPERATOR,
        proposed_refund=refund_request(key="durable-refund-1"),
    )

    paused = durable_workflow(factory, checkpointer, lifecycle, action_tools=tools).start(
        initial_request
    )

    assert isinstance(paused, WorkflowPause)
    assert paused.status == WorkflowStatus.WAITING_APPROVAL
    assert paused.approval.status == ApprovalStatus.PENDING
    assert lifecycle.get_run(initial_request.workflow_id).status == (
        WorkflowLifecycleStatus.WAITING_APPROVAL
    )
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(RefundRecord)) == 1
        assert session.scalar(select(func.count()).select_from(WorkflowApprovalRecord)) == 1

    restarted_lifecycle = WorkflowLifecycleStore(
        factory,
        clock=lambda: NOW,
        id_generator=event_ids,
    )
    restarted = durable_workflow(
        factory,
        checkpointer,
        restarted_lifecycle,
        action_tools=tools,
    )
    assert restarted.get_execution(initial_request.workflow_id) == paused
    assert restarted.start(initial_request) == paused

    approval_decision = WorkflowApprovalDecision(
        approval_id=paused.approval.approval_id,
        decision=ApprovalDecisionType.APPROVE,
        actor=actor(ActorRole.APPROVER),
        note="Verified duplicate payment and approved the refund.",
    )
    result = restarted.resume(approval_decision)

    assert not isinstance(result, WorkflowPause)
    assert result.outcome == WorkflowOutcome.ACTION_VERIFIED
    assert result.status == WorkflowStatus.COMPLETED
    assert result.operation is not None
    assert result.operation.verified is True
    assert restarted_lifecycle.get_run(initial_request.workflow_id).status == (
        WorkflowLifecycleStatus.COMPLETED
    )
    assert [
        event.event_type for event in restarted_lifecycle.list_events(initial_request.workflow_id)
    ] == [
        WorkflowEventType.STARTED,
        WorkflowEventType.APPROVAL_REQUESTED,
        WorkflowEventType.APPROVAL_APPROVED,
        WorkflowEventType.COMPLETED,
    ]
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(RefundRecord)) == 2
        assert session.scalar(select(func.count()).select_from(WorkflowApprovalRecord)) == 1

    assert restarted.resume(approval_decision) == result
    with pytest.raises(ApprovalDecisionError, match="already approved"):
        restarted.resume(
            approval_decision.model_copy(update={"note": "A conflicting replay note."})
        )


def test_durable_workflow_rejection_finishes_without_refund(
    workflow_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = workflow_database
    make_duplicate_issue_actionable(factory)
    checkpointer = InMemorySaver()
    lifecycle = WorkflowLifecycleStore(factory, clock=lambda: NOW, id_generator=ids())
    initial_request = request(
        role=ActorRole.OPERATOR,
        proposed_refund=refund_request(key="durable-refund-rejected"),
    )
    durable = durable_workflow(factory, checkpointer, lifecycle)
    paused = durable.start(initial_request)
    assert isinstance(paused, WorkflowPause)

    result = durable.resume(
        WorkflowApprovalDecision(
            approval_id=paused.approval.approval_id,
            decision=ApprovalDecisionType.REJECT,
            actor=actor(ActorRole.APPROVER),
            note="The duplicate payment evidence needs manual reconciliation.",
        )
    )

    assert not isinstance(result, WorkflowPause)
    assert result.outcome == WorkflowOutcome.NEEDS_REVIEW
    assert result.error_code == "approval_rejected"
    assert lifecycle.get_run(initial_request.workflow_id).status == (
        WorkflowLifecycleStatus.ESCALATED
    )
    assert [event.event_type for event in lifecycle.list_events(initial_request.workflow_id)][
        -2:
    ] == [
        WorkflowEventType.APPROVAL_REJECTED,
        WorkflowEventType.ESCALATED,
    ]
    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(RefundRecord)
                .where(RefundRecord.issue_id == "ISSUE-1001")
            )
            == 0
        )


def test_unauthorized_approval_keeps_workflow_paused(
    workflow_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = workflow_database
    make_duplicate_issue_actionable(factory)
    checkpointer = InMemorySaver()
    lifecycle = WorkflowLifecycleStore(factory, clock=lambda: NOW, id_generator=ids())
    durable = durable_workflow(factory, checkpointer, lifecycle)
    paused = durable.start(
        request(
            role=ActorRole.OPERATOR,
            proposed_refund=refund_request(key="durable-refund-unauthorized"),
        )
    )
    assert isinstance(paused, WorkflowPause)

    with pytest.raises(ApprovalDecisionError, match="only an approver"):
        durable.resume(
            WorkflowApprovalDecision(
                approval_id=paused.approval.approval_id,
                decision=ApprovalDecisionType.APPROVE,
                actor=actor(ActorRole.OPERATOR),
                note="Attempted approval without the approver role.",
            )
        )

    still_paused = durable.get_execution(paused.workflow_id)
    assert isinstance(still_paused, WorkflowPause)
    assert lifecycle.get_approval(paused.approval.approval_id).status == (ApprovalStatus.PENDING)


def test_durable_workflow_executes_without_pause_inside_actor_limit(
    workflow_database: tuple[Engine, sessionmaker[Session]],
) -> None:
    _, factory = workflow_database
    make_duplicate_issue_actionable(factory)
    checkpointer = InMemorySaver()
    lifecycle = WorkflowLifecycleStore(factory, clock=lambda: NOW, id_generator=ids())
    durable = durable_workflow(factory, checkpointer, lifecycle)

    result = durable.start(
        request(
            role=ActorRole.APPROVER,
            proposed_refund=refund_request(key="durable-refund-direct"),
        )
    )

    assert not isinstance(result, WorkflowPause)
    assert result.outcome == WorkflowOutcome.ACTION_VERIFIED
    assert lifecycle.get_run(result.workflow_id).status == WorkflowLifecycleStatus.COMPLETED
