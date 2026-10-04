"""Business-outcome evaluation through the normal, durable customer workflow.

Expectations are scorer-only. Providers receive the new complaint and the application's
read tools, never task IDs, fixture names, expected dispositions or expected outcomes.
Approval and settlement are explicitly synthetic test actions, not human review.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Literal

from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from resolveops.agents.grounding import observation_context
from resolveops.agents.models import AgentRole, ToolRequest
from resolveops.agents.persistence import AgentRunStore
from resolveops.agents.runtime import MultiAgentReasoningRuntime
from resolveops.agents.tools import AgentReadToolRegistry, AgentToolResult
from resolveops.database.base import Base
from resolveops.database.knowledge_records import KnowledgeDocumentRecord
from resolveops.database.records import PaymentRecord, RefundRecord, ReturnRecord
from resolveops.database.seed import seed_all
from resolveops.database.session import create_session_factory
from resolveops.database.store import CustomerOperationsStore
from resolveops.events.models import RefundStatusChangedData, RefundStatusChangedEvent
from resolveops.events.processor import RefundEventProcessor
from resolveops.intake.service import CaseIntakeService, IntakeRequest
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.knowledge.ingestion import ingest_directory
from resolveops.knowledge.models import KnowledgeStatus
from resolveops.models.case import CaseIssueType
from resolveops.models.payment import PaymentStatus
from resolveops.models.refund import RefundKind, RefundStatus
from resolveops.models.returns import ReturnStatus
from resolveops.operations.models import Actor, ActorRole
from resolveops.orchestration.graph import HierarchicalAgentOrchestrator
from resolveops.workflows.customer_issue import CustomerIssueWorkflow
from resolveops.workflows.lifecycle import WorkflowLifecycleStore
from resolveops.workflows.models import (
    ApprovalDecisionType,
    WorkflowApprovalDecision,
    WorkflowOutcome,
    WorkflowPause,
    WorkflowRequest,
    WorkflowResult,
)

COMPLAINT = (
    "I was charged twice for this order. I also returned the coffee grinder and have "
    "not received my refund. Please check both issues and whether a refund already "
    "exists before starting another one."
)
TENANT = "TENANT-INTEGRATED-EVALUATION"


def summarize_integrated_trials(records: list[dict[str, object]]) -> dict[str, int]:
    """Separate completed business runs from clean provider calls and correct outcomes."""
    completed = 0
    for record in records:
        checks = record.get("checks")
        if (
            record.get("error") is None
            and isinstance(record.get("workflow_result"), dict)
            and isinstance(checks, dict)
            and checks.get("agent_executed_when_configured") is True
        ):
            completed += 1
    return {
        "completed_trials": completed,
        "trials_without_provider_failures": sum(
            not bool(record.get("provider_failures")) for record in records
        ),
        "correct_trials": sum(bool(record.get("passed")) for record in records),
    }


class IntegratedTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evaluation_id: str
    fixture: Literal[
        "normal",
        "prior_duplicate_refund",
        "split_captures",
        "authorization_only",
        "missing_obligation",
        "missing_policy",
        "no_return_refund",
        "return_in_transit",
    ]
    target_issue: CaseIssueType
    approval: Literal["approve", "reject"]
    settlement: Literal["completed"] | None
    expected_outcome: WorkflowOutcome
    expected_new_refunds: int = Field(ge=0, le=1)
    expected_amount: Decimal | None = None
    expected_payment_id: str | None = None
    expected_final_issue: str


def load_integrated_tasks(path: Path) -> list[IntegratedTask]:
    tasks = [
        IntegratedTask.model_validate_json(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    if len({task.evaluation_id for task in tasks}) != len(tasks):
        raise ValueError("evaluation IDs must be unique")
    return tasks


class RecordingReadTools(AgentReadToolRegistry):
    """Retain actual, scoped observations only for synthetic evaluation artifacts."""

    observations: list[dict[str, object]]

    def __init__(self, factory: sessionmaker[Session], clock: Callable[[], datetime]) -> None:
        super().__init__(
            factory, FeatureHashEmbeddingProvider(dimensions=128), tenant_id=TENANT, clock=clock
        )
        self.observations = []

    def execute(self, role: AgentRole, request: ToolRequest) -> AgentToolResult:
        result = super().execute(role, request)
        self.observations.append(
            {
                "role": role.value,
                "request": request.model_dump(mode="json"),
                "observation": observation_context(result),
            }
        )
        return result


RuntimeBuilder = Callable[[sessionmaker[Session]], MultiAgentReasoningRuntime]


def _prepare_fixture(session: Session, task: IntegratedTask, now: datetime) -> None:
    payment = session.get(PaymentRecord, "PAY-1002")
    assert payment is not None
    if task.fixture == "prior_duplicate_refund":
        session.add(
            RefundRecord(
                refund_id="REF-PRIOR-CAPTURE",
                payment_id="PAY-1002",
                order_id="ORD-48391",
                issue_id="ISSUE-1001",
                return_id=None,
                amount=Decimal("1499.00"),
                currency="USD",
                status=RefundStatus.PENDING,
                kind=RefundKind.DUPLICATE_CHARGE,
                reason="Existing refund submitted by another support case",
                created_at=now - timedelta(hours=1),
                completed_at=None,
            )
        )
    elif task.fixture == "split_captures":
        first = session.get(PaymentRecord, "PAY-1001")
        assert first is not None
        first.amount = payment.amount = Decimal("749.50")
        first.obligation_id = "OBL-PART-A"
        payment.obligation_id = "OBL-PART-B"
        first.obligation_amount = payment.obligation_amount = Decimal("749.50")
    elif task.fixture == "authorization_only":
        payment.status = PaymentStatus.AUTHORIZED
        payment.captured_at = None
    elif task.fixture == "missing_obligation":
        payment.obligation_id = None
        payment.obligation_amount = None
    elif task.fixture == "missing_policy":
        for document in session.scalars(
            select(KnowledgeDocumentRecord).where(
                KnowledgeDocumentRecord.document_id == "POLICY-DUPLICATE-CHARGE"
            )
        ):
            document.status = KnowledgeStatus.SUPERSEDED
    elif task.fixture in {"no_return_refund", "return_in_transit"}:
        refund = session.get(RefundRecord, "REF-2001")
        assert refund is not None
        session.delete(refund)
        if task.fixture == "return_in_transit":
            returned = session.get(ReturnRecord, "RET-3001")
            assert returned is not None
            returned.status = ReturnStatus.IN_TRANSIT
            returned.received_at = None
    session.flush()


def run_integrated_trial(
    task: IntegratedTask,
    trial: int,
    *,
    policy_directory: Path,
    runtime_builder: RuntimeBuilder | None = None,
    execution_mode: str = "rules_only",
) -> dict[str, object]:
    """Create isolated source records, submit new intake, approve and score final state."""
    if (runtime_builder is None) != (execution_mode == "rules_only"):
        raise ValueError("an agent execution mode requires an actual runtime builder")
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(connection: object, _: object) -> None:
        connection.execute("PRAGMA foreign_keys=ON")  # type: ignore[attr-defined]

    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    now = datetime.now(UTC)
    embeddings = FeatureHashEmbeddingProvider(dimensions=128)
    try:
        with factory.begin() as session:
            seed_all(session)
            ingest_directory(session, policy_directory, embeddings, ingested_at=now)
            _prepare_fixture(session, task, now)
            intake, _ = CaseIntakeService(session, clock=lambda: now).submit(
                IntakeRequest(
                    customer_id="CUST-1001",
                    order_id="ORD-48391",
                    complaint=COMPLAINT,
                    source_message_id="SYNTHETIC-EVALUATION-RECEIPT",
                )
            )
            initial_case = intake.model_dump(mode="json")
            target_issue = next(
                issue for issue in intake.issues if issue.issue_type == task.target_issue
            )
            initial_refunds = set(session.scalars(select(RefundRecord.refund_id)))
            store = CustomerOperationsStore(session)
            source_records = {
                "order": store.get_order(intake.order_id).model_dump(mode="json"),  # type: ignore[union-attr]
                "payments": [
                    row.model_dump(mode="json") for row in store.list_payments(intake.order_id)
                ],
                "returns": [
                    store.get_return(row).model_dump(mode="json")  # type: ignore[union-attr]
                    for row in session.scalars(
                        select(ReturnRecord.return_id).where(
                            ReturnRecord.order_id == intake.order_id
                        )
                    )
                ],
                "refunds": [
                    store.get_refund(row).model_dump(mode="json")  # type: ignore[union-attr]
                    for row in session.scalars(
                        select(RefundRecord.refund_id).where(
                            RefundRecord.order_id == intake.order_id
                        )
                    )
                ],
            }
        tools = RecordingReadTools(factory, lambda: datetime.now(UTC))
        runtime = runtime_builder(factory) if runtime_builder else None
        if runtime:
            runtime.tools = tools
        lifecycle = WorkflowLifecycleStore(factory)
        workflow = CustomerIssueWorkflow(
            factory,
            embeddings,
            agent_runtime=HierarchicalAgentOrchestrator(runtime) if runtime else None,
            tenant_id=TENANT,
            model_execution_mode=execution_mode,
            checkpointer=InMemorySaver(),
            lifecycle_store=lifecycle,
        )
        # The opaque workflow/case identifiers reveal no fixture or expected answer.
        workflow_id = f"WF-{intake.case_id}"
        approval_decision = None
        settlement_event = None
        settlement_receipt = None
        outcome: WorkflowResult | WorkflowPause | None = None
        error = None
        started = perf_counter()
        refunds_after_investigation = initial_refunds
        try:
            outcome = workflow.start(
                WorkflowRequest(
                    workflow_id=workflow_id,
                    case_id=intake.case_id,
                    issue_id=target_issue.issue_id,
                    actor=Actor(actor_id="SYNTHETIC-TEST-OPERATOR", role=ActorRole.OPERATOR),
                    investigation_only=True,
                )
            )
            with factory() as session:
                refunds_after_investigation = set(session.scalars(select(RefundRecord.refund_id)))
            if isinstance(outcome, WorkflowPause):
                approval_decision = WorkflowApprovalDecision(
                    approval_id=outcome.approval.approval_id,
                    decision=ApprovalDecisionType(task.approval),
                    actor=Actor(actor_id="SYNTHETIC-TEST-APPROVER", role=ActorRole.APPROVER),
                    note="Synthetic evaluation decision; not human-reviewed evidence.",
                )
                outcome = workflow.resume(approval_decision)
            if (
                isinstance(outcome, WorkflowResult)
                and task.settlement
                and outcome.outcome == WorkflowOutcome.REFUND_SUBMITTED
            ):
                event_time = datetime.now(UTC) + timedelta(seconds=1)
                settlement_event = RefundStatusChangedEvent(
                    event_id=f"SYNTHETIC-SETTLEMENT-{trial}",
                    source="synthetic-evaluation-provider",
                    occurred_at=event_time,
                    data=RefundStatusChangedData(
                        refund_id=str(outcome.verified_resource_id),
                        provider_reference="SYNTHETIC-EVALUATION-REFERENCE",
                        status=RefundStatus.COMPLETED,
                        completed_at=event_time,
                    ),
                )
                settlement_receipt = RefundEventProcessor(
                    factory, clock=lambda: event_time
                ).process(settlement_event)
        except Exception as exc:  # noqa: BLE001 - a failed attempted trial remains scored evidence
            # Every attempted provider/workflow failure is retained, never dropped.
            error = {
                "classification": getattr(exc, "code", type(exc).__name__),
                "message": str(exc)[:300],
            }
        latency_ms = (perf_counter() - started) * 1000
        with factory() as session:
            store = CustomerOperationsStore(session)
            final_case = store.get_case(intake.case_id)
            assert final_case is not None
            final_issue = next(
                issue for issue in final_case.issues if issue.issue_id == target_issue.issue_id
            )
            new_ids = set(session.scalars(select(RefundRecord.refund_id))) - initial_refunds
            new_refunds = [store.get_refund(refund_id) for refund_id in sorted(new_ids)]
        result = outcome if isinstance(outcome, WorkflowResult) else None
        checks = {
            "completed_without_exception": error is None,
            "new_intake_not_preconfirmed": all(
                issue["finding"] == "undetermined" for issue in initial_case["issues"]
            ),
            "investigation_read_only": refunds_after_investigation == initial_refunds,
            "business_outcome": bool(result and result.outcome == task.expected_outcome),
            "new_refund_count": len(new_refunds) == task.expected_new_refunds,
            "refund_amount_and_target": all(
                refund is not None
                and (
                    refund.amount == task.expected_amount
                    and refund.payment_id == task.expected_payment_id
                )
                for refund in new_refunds
            ),
            "explicit_approval_before_write": not new_refunds
            or bool(
                approval_decision and approval_decision.decision == ApprovalDecisionType.APPROVE
            ),
            "final_issue_state": final_issue.status.value == task.expected_final_issue,
            "settlement_state": not task.settlement
            or bool(
                new_refunds
                and all(
                    refund and refund.status == RefundStatus.COMPLETED for refund in new_refunds
                )
            ),
            "agent_executed_when_configured": runtime is None
            or bool(result and result.agent_assessment),
        }
        agent_store = AgentRunStore(factory)
        runs = agent_store.list_for_workflow(workflow_id)
        calls = agent_store.list_tool_calls_for_workflow(workflow_id)
        provider_failures = [row.error_classification for row in runs if row.error_classification]
        tokens_known = bool(runs) and all(
            row.input_tokens is not None and row.output_tokens is not None for row in runs
        )
        return {
            "evaluation_id": task.evaluation_id,
            "trial": trial,
            "passed": all(checks.values()),
            "checks": checks,
            "evaluation_scope": "normal_customer_workflow_business_outcome",
            "execution_mode": execution_mode,
            "environment": "local_isolated_sqlite",
            "tool_source": "application_read_tools_and_seeded_source_records",
            "approval_review": "synthetic_test_decision_not_human_review",
            "provider_events": "synthetic_simulator_not_external_payment_provider",
            "routing": "sequential_roles_with_deterministic_early_safety_stops"
            if runtime
            else "rules_only",
            "limits": [
                "Not an HTTP authentication or deployed test",
                "Single-agent comparison not implemented",
                "No human response-quality labels",
            ],
            "expected": task.model_dump(mode="json"),
            "input": {
                "case": initial_case,
                "source_records": source_records,
                "target_issue_id": target_issue.issue_id,
            },
            "tool_observations": tools.observations,
            "agent_runs": [row.model_dump(mode="json") for row in runs],
            "provider_failures": provider_failures,
            "input_tokens": sum(row.input_tokens or 0 for row in runs) if tokens_known else None,
            "output_tokens": sum(row.output_tokens or 0 for row in runs) if tokens_known else None,
            "cost_usd": runtime.ledger.usage.estimated_cost_usd
            if runtime and tokens_known
            else None,
            "tool_calls": [row.model_dump(mode="json") for row in calls],
            "approval_decision": approval_decision.model_dump(mode="json")
            if approval_decision
            else None,
            "workflow_events": [
                row.model_dump(mode="json") for row in lifecycle.list_events(workflow_id)
            ],
            "workflow_result": outcome.model_dump(mode="json") if outcome else None,
            "settlement_event": settlement_event.model_dump(mode="json")
            if settlement_event
            else None,
            "settlement_receipt": settlement_receipt.model_dump(mode="json")
            if settlement_receipt
            else None,
            "final_case": final_case.model_dump(mode="json"),
            "new_refunds": [refund.model_dump(mode="json") for refund in new_refunds if refund],
            "final_workflow": lifecycle.get_run(workflow_id).model_dump(mode="json"),
            "model_calls": len(runs),
            "tool_call_count": len(calls),
            "latency_ms": latency_ms,
            "budget": runtime.ledger.budget.model_dump(mode="json") if runtime else None,
            "max_investigation_turns": runtime.max_investigation_turns if runtime else None,
            "usage": runtime.ledger.usage.model_dump(mode="json") if runtime else None,
            "error": error,
        }
    finally:
        engine.dispose()
