from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from resolveops.database.base import Base
from resolveops.database.records import (
    CaseIssueEvidenceRecord,
    CaseIssueRecord,
    CaseIssueResolutionRecord,
    CaseIssueVerificationRecord,
    CaseRecord,
    RefundRecord,
)
from resolveops.database.seed import seed_all
from resolveops.database.session import create_session_factory
from resolveops.database.workflow_records import WorkflowEventRecord
from resolveops.events.models import InboundEventStatus, RefundStatusChangedEvent
from resolveops.events.processor import RefundEventProcessor
from resolveops.models.case import (
    CaseIssueStatus,
    CaseIssueType,
    CaseStatus,
    IssueFinding,
    VerificationStatus,
)
from resolveops.models.refund import RefundStatus
from resolveops.operations.models import (
    Actor,
    ActorRole,
    OperationResult,
    OperationStatus,
    OperationType,
)
from resolveops.responses.customer import CustomerResponseComposer
from resolveops.workflows.case_state import (
    refresh_refund_result,
    synchronize_case_state,
    synchronize_refund_state,
)
from resolveops.workflows.lifecycle import WorkflowLifecycleStore
from resolveops.workflows.models import (
    WorkflowDecision,
    WorkflowEventType,
    WorkflowLifecycleStatus,
    WorkflowOutcome,
    WorkflowRequest,
    WorkflowResult,
    WorkflowStatus,
)

NOW = datetime(2026, 10, 4, 14, 0, tzinfo=UTC)


@pytest.fixture
def settlement_database() -> Iterator[sessionmaker[Session]]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with factory.begin() as session:
        seed_all(session)
    yield factory
    engine.dispose()


def submission_result() -> WorkflowResult:
    # An old durable checkpoint still says action_verified. The ledger must win.
    response = CustomerResponseComposer().compose(
        status=WorkflowStatus.COMPLETED,
        outcome=WorkflowOutcome.ACTION_VERIFIED,
        issue_id="ISSUE-1002",
        verified_resource_id="REF-2001",
        existing_refund_id=None,
        error_code=None,
        policy_citations=[],
        generated_at=NOW,
    )
    return WorkflowResult(
        workflow_id="WF-SETTLEMENT",
        case_id="CASE-1001",
        issue_id="ISSUE-1002",
        status=WorkflowStatus.COMPLETED,
        outcome=WorkflowOutcome.ACTION_VERIFIED,
        issue_type=CaseIssueType.MISSING_RETURN_REFUND,
        finding=IssueFinding.CONFIRMED,
        decision=WorkflowDecision.EXECUTE_REFUND,
        evidence=["The received return and refund submission are recorded."],
        policy_citations=[],
        operation=OperationResult(
            operation_id="OP-SETTLEMENT",
            operation_type=OperationType.ISSUE_REFUND,
            resource_id="REF-2001",
            status=OperationStatus.COMPLETED,
            verified=True,
        ),
        verified_resource_id="REF-2001",
        resolution_summary="Submission verified, awaiting settlement.",
        final_response=response,
        node_history=["verify_action"],
    )


def status_event(
    status: str,
    *,
    event_id: str = "EVT-SETTLEMENT",
    occurred_at: datetime = NOW,
    refund_id: str = "REF-2001",
) -> RefundStatusChangedEvent:
    return RefundStatusChangedEvent.model_validate(
        {
            "event_id": event_id,
            "source": "payment-provider-sandbox",
            "occurred_at": occurred_at,
            "data": {
                "refund_id": refund_id,
                "provider_reference": f"PROVIDER-{refund_id}",
                "status": status,
                "completed_at": occurred_at if status == "completed" else None,
            },
        }
    )


def test_submission_keeps_issue_open_and_refreshes_legacy_result(
    settlement_database: sessionmaker[Session],
) -> None:
    factory = settlement_database
    original = submission_result()
    synchronize_case_state(factory, original, lambda: NOW)
    result = refresh_refund_result(factory, original, lambda: NOW)
    assert result.outcome == WorkflowOutcome.REFUND_SUBMITTED
    assert result.status == WorkflowStatus.WAITING_EXTERNAL
    assert "Settlement is still pending" in result.final_response.message
    with factory() as session:
        issue = session.get(CaseIssueRecord, "ISSUE-1002")
        verification = session.get(CaseIssueVerificationRecord, "ISSUE-1002")
        case = session.get(CaseRecord, "CASE-1001")
        assert issue is not None and issue.status == CaseIssueStatus.VERIFYING
        assert verification is not None and verification.status == VerificationStatus.PENDING
        assert case is not None and case.status == CaseStatus.IN_PROGRESS
        assert session.get(CaseIssueResolutionRecord, "ISSUE-1002") is None


def test_stale_session_refund_is_reloaded_before_case_projection(
    settlement_database: sessionmaker[Session],
) -> None:
    factory = settlement_database
    with factory() as stale_session:
        old = stale_session.get(RefundRecord, "REF-2001")
        assert old is not None and old.status == RefundStatus.PENDING
        RefundEventProcessor(factory, clock=lambda: NOW).process(status_event("completed"))
        assert old.status == RefundStatus.PENDING
        projection = synchronize_refund_state(stale_session, old, NOW)
        stale_session.commit()
        assert projection.outcome == WorkflowOutcome.REFUND_SETTLED
    with factory() as session:
        issue = session.get(CaseIssueRecord, "ISSUE-1002")
        assert issue is not None and issue.status == CaseIssueStatus.RESOLVED


def test_settlement_resolves_only_its_issue_and_old_checkpoint_cannot_reopen_it(
    settlement_database: sessionmaker[Session],
) -> None:
    factory = settlement_database
    processor = RefundEventProcessor(factory, clock=lambda: NOW)
    receipt = processor.process(status_event("completed"))
    assert receipt.status == InboundEventStatus.PROCESSED
    result = refresh_refund_result(factory, submission_result(), lambda: NOW)
    assert result.outcome == WorkflowOutcome.REFUND_SETTLED
    assert "has settled" in result.final_response.message
    synchronize_case_state(factory, submission_result(), lambda: NOW)
    with factory() as session:
        issue = session.get(CaseIssueRecord, "ISSUE-1002")
        sibling = session.get(CaseIssueRecord, "ISSUE-1001")
        verification = session.get(CaseIssueVerificationRecord, "ISSUE-1002")
        case = session.get(CaseRecord, "CASE-1001")
        assert issue is not None and issue.status == CaseIssueStatus.RESOLVED
        assert sibling is not None and sibling.status != CaseIssueStatus.RESOLVED
        assert verification is not None and verification.status == VerificationStatus.PASSED
        assert case is not None and case.status == CaseStatus.IN_PROGRESS


@pytest.mark.parametrize("status", ["failed", "cancelled"])
def test_unsuccessful_settlement_keeps_actionable_case_and_truthful_response(
    settlement_database: sessionmaker[Session], status: str
) -> None:
    factory = settlement_database
    processor = RefundEventProcessor(factory, clock=lambda: NOW)
    processor.process(status_event(status))
    result = refresh_refund_result(factory, submission_result(), lambda: NOW)
    assert result.outcome == WorkflowOutcome.NEEDS_REVIEW
    assert result.error_code == f"refund_{status}"
    assert "operator" in result.final_response.message
    assert "replacement refund" in result.final_response.message
    with factory() as session:
        issue = session.get(CaseIssueRecord, "ISSUE-1002")
        case = session.get(CaseRecord, "CASE-1001")
        verification = session.get(CaseIssueVerificationRecord, "ISSUE-1002")
        assert issue is not None and issue.status == CaseIssueStatus.ESCALATED
        assert case is not None and case.status == CaseStatus.ESCALATED
        assert verification is not None and verification.status == VerificationStatus.FAILED
        assert session.get(CaseIssueResolutionRecord, "ISSUE-1002") is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(RefundRecord)
                .where(RefundRecord.issue_id == "ISSUE-1002")
            )
            == 1
        )


def test_duplicate_and_older_events_do_not_regress_settled_case(
    settlement_database: sessionmaker[Session],
) -> None:
    factory = settlement_database
    processor = RefundEventProcessor(factory, clock=lambda: NOW)
    event = status_event("completed")
    assert processor.process(event).status == InboundEventStatus.PROCESSED
    assert processor.process(event).idempotent_replay
    old = processor.process(
        status_event("processing", event_id="EVT-OLDER", occurred_at=NOW - timedelta(seconds=1))
    )
    assert old.status == InboundEventStatus.IGNORED_STALE
    rejected = processor.process(
        status_event("failed", event_id="EVT-REGRESSION", occurred_at=NOW + timedelta(seconds=1))
    )
    assert rejected.status == InboundEventStatus.REJECTED
    with factory() as session:
        issue = session.get(CaseIssueRecord, "ISSUE-1002")
        assert issue is not None and issue.status == CaseIssueStatus.RESOLVED
        observations = session.scalar(
            select(func.count())
            .select_from(CaseIssueEvidenceRecord)
            .where(CaseIssueEvidenceRecord.source == "payment-provider-status")
        )
        assert observations == 1


def test_same_timestamp_forward_transition_is_not_discarded(
    settlement_database: sessionmaker[Session],
) -> None:
    processor = RefundEventProcessor(settlement_database, clock=lambda: NOW)
    processor.process(status_event("processing", event_id="EVT-PROCESSING"))
    completed = processor.process(status_event("completed"))
    assert completed.status == InboundEventStatus.PROCESSED
    with settlement_database() as session:
        refund = session.get(RefundRecord, "REF-2001")
        assert refund is not None and refund.status == RefundStatus.COMPLETED


def test_partial_settlement_does_not_close_full_return_issue(
    settlement_database: sessionmaker[Session],
) -> None:
    factory = settlement_database
    with factory.begin() as session:
        refund = session.get(RefundRecord, "REF-2001")
        assert refund is not None
        refund.amount = Decimal("100.00")
    RefundEventProcessor(factory, clock=lambda: NOW).process(status_event("completed"))
    result = refresh_refund_result(factory, submission_result(), lambda: NOW)
    assert result.outcome == WorkflowOutcome.NEEDS_REVIEW
    assert result.error_code == "refund_settlement_incomplete"
    with factory() as session:
        issue = session.get(CaseIssueRecord, "ISSUE-1002")
        assert issue is not None and issue.status == CaseIssueStatus.ESCALATED


def test_all_required_refund_portions_must_settle(
    settlement_database: sessionmaker[Session],
) -> None:
    factory = settlement_database
    with factory.begin() as session:
        original = session.get(RefundRecord, "REF-2001")
        assert original is not None
        original.amount = Decimal("100.00")
        session.add(
            RefundRecord(
                refund_id="REF-REMAINING",
                payment_id=original.payment_id,
                order_id=original.order_id,
                issue_id=original.issue_id,
                return_id=original.return_id,
                amount=Decimal("100.00"),
                currency=original.currency,
                status=RefundStatus.PENDING,
                kind=original.kind,
                reason="Remaining received-return refund",
                created_at=original.created_at + timedelta(minutes=1),
                completed_at=None,
            )
        )
    processor = RefundEventProcessor(factory, clock=lambda: NOW)
    lifecycle = WorkflowLifecycleStore(factory, clock=lambda: NOW)
    lifecycle.start(
        WorkflowRequest(
            workflow_id="WF-SETTLEMENT",
            case_id="CASE-1001",
            issue_id="ISSUE-1002",
            actor=Actor(actor_id="OPERATOR-1", role=ActorRole.OPERATOR),
        )
    )
    lifecycle.finish(refresh_refund_result(factory, submission_result(), lambda: NOW))
    processor.process(status_event("completed"))
    with factory() as session:
        issue = session.get(CaseIssueRecord, "ISSUE-1002")
        assert issue is not None and issue.status == CaseIssueStatus.VERIFYING
    processor.process(
        status_event("completed", event_id="EVT-REMAINING", refund_id="REF-REMAINING")
    )
    with factory() as session:
        issue = session.get(CaseIssueRecord, "ISSUE-1002")
        assert issue is not None and issue.status == CaseIssueStatus.RESOLVED
    assert lifecycle.get_run("WF-SETTLEMENT").outcome == WorkflowOutcome.REFUND_SETTLED


@pytest.mark.parametrize("replacement_delay", [0, 1])
def test_old_failed_attempt_cannot_overwrite_successful_recovery_projection(
    settlement_database: sessionmaker[Session],
    replacement_delay: int,
) -> None:
    factory = settlement_database
    with factory.begin() as session:
        original = session.get(RefundRecord, "REF-2001")
        assert original is not None
        original.created_at = NOW
    processor = RefundEventProcessor(factory, clock=lambda: NOW + timedelta(minutes=2))
    processor.process(status_event("failed"))
    with factory.begin() as session:
        original = session.get(RefundRecord, "REF-2001")
        assert original is not None
        session.add(
            RefundRecord(
                refund_id="REF-REPLACEMENT",
                payment_id=original.payment_id,
                order_id=original.order_id,
                issue_id=original.issue_id,
                return_id=original.return_id,
                amount=original.amount,
                currency=original.currency,
                status=RefundStatus.PENDING,
                kind=original.kind,
                reason="Separately authorized replacement after provider failure",
                created_at=NOW + timedelta(seconds=replacement_delay),
                completed_at=None,
            )
        )
    processor.process(
        status_event(
            "completed",
            event_id="EVT-REPLACEMENT",
            refund_id="REF-REPLACEMENT",
            occurred_at=NOW + timedelta(minutes=1),
        )
    )
    old = refresh_refund_result(factory, submission_result(), lambda: NOW + timedelta(minutes=2))
    assert old.error_code == "refund_failed"
    synchronize_case_state(factory, old, lambda: NOW + timedelta(minutes=2))
    with factory() as session:
        issue = session.get(CaseIssueRecord, "ISSUE-1002")
        assert issue is not None and issue.status == CaseIssueStatus.RESOLVED


def test_provider_reference_and_impossible_completion_time_are_rejected(
    settlement_database: sessionmaker[Session],
) -> None:
    factory = settlement_database
    processor = RefundEventProcessor(factory, clock=lambda: NOW)
    processor.process(status_event("processing", event_id="EVT-PROCESSING"))
    wrong_reference = status_event("completed").model_copy(
        update={
            "data": status_event("completed").data.model_copy(
                update={
                    "provider_reference": "OTHER-PROVIDER-REFUND",
                }
            ),
        }
    )
    assert processor.process(wrong_reference).status == InboundEventStatus.REJECTED
    impossible_time = status_event("completed", event_id="EVT-IMPOSSIBLE").model_copy(
        update={
            "data": status_event("completed").data.model_copy(
                update={
                    "completed_at": NOW + timedelta(hours=1),
                }
            ),
        }
    )
    assert processor.process(impossible_time).status == InboundEventStatus.REJECTED
    with factory() as session:
        refund = session.get(RefundRecord, "REF-2001")
        assert refund is not None and refund.status == RefundStatus.PROCESSING


def test_settlement_updates_waiting_workflow_and_appends_one_replay_safe_event(
    settlement_database: sessionmaker[Session],
) -> None:
    factory = settlement_database
    lifecycle = WorkflowLifecycleStore(factory, clock=lambda: NOW)
    lifecycle.start(
        WorkflowRequest(
            workflow_id="WF-SETTLEMENT",
            case_id="CASE-1001",
            issue_id="ISSUE-1002",
            actor=Actor(actor_id="OPERATOR-1", role=ActorRole.OPERATOR),
        )
    )
    submitted = refresh_refund_result(factory, submission_result(), lambda: NOW)
    lifecycle.finish(submitted)
    processor = RefundEventProcessor(factory, clock=lambda: NOW)
    event = status_event("completed")
    processor.process(event)
    processor.process(event)
    run = lifecycle.get_run("WF-SETTLEMENT")
    assert run.status == WorkflowLifecycleStatus.COMPLETED
    assert run.outcome == WorkflowOutcome.REFUND_SETTLED
    with factory() as session:
        events = list(
            session.scalars(
                select(WorkflowEventRecord).where(
                    WorkflowEventRecord.workflow_id == "WF-SETTLEMENT",
                    WorkflowEventRecord.event_type == WorkflowEventType.REFUND_STATUS_CHANGED,
                )
            )
        )
        matching = [
            item for item in events if item.details.get("inbound_event_id") == event.event_id
        ]
        assert len(matching) == 1
