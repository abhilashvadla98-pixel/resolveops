from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from resolveops.api.dependencies import get_principal, get_tenant_session
from resolveops.database.session import create_session_factory
from resolveops.database.store import CustomerOperationsStore
from resolveops.intake import CaseIntakeService, IntakeRequest
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.models.case import Case
from resolveops.models.common import AwareDatetime, DomainModel, Identifier, NonEmptyText
from resolveops.operations.auth import has_permission
from resolveops.operations.models import IssueRefundRequest, Permission
from resolveops.security.models import SecurityPrincipal
from resolveops.workflows.checkpointing import checkpoint_serializer, open_postgres_checkpointer
from resolveops.workflows.customer_issue import CustomerIssueWorkflow
from resolveops.workflows.lifecycle import (
    ApprovalDecisionError,
    WorkflowLifecycleError,
    WorkflowLifecycleStore,
)
from resolveops.workflows.models import (
    ApprovalDecisionType,
    ApprovalStatus,
    WorkflowApproval,
    WorkflowApprovalDecision,
    WorkflowEvent,
    WorkflowPause,
    WorkflowRequest,
    WorkflowResult,
)

router = APIRouter(prefix="/api/v1", tags=["operations"])
DatabaseSession = Annotated[Session, Depends(get_tenant_session)]
Principal = Annotated[SecurityPrincipal, Depends(get_principal)]

_sqlite_checkpointers: dict[int, InMemorySaver] = {}
_checkpointer_lock = Lock()


class ComplaintSubmission(DomainModel):
    customer_id: Identifier
    order_id: Identifier
    complaint: str = Field(min_length=1, max_length=4000)


class StartWorkflow(DomainModel):
    workflow_id: Identifier
    case_id: Identifier
    issue_id: Identifier
    refund_request: IssueRefundRequest | None = None


class ApprovalDecision(DomainModel):
    decision: ApprovalDecisionType
    note: NonEmptyText


class CaseTimelineEvent(DomainModel):
    event_id: Identifier
    event_type: Identifier
    occurred_at: AwareDatetime
    entity_id: Identifier
    details: dict[str, Any]


def _require_operations_access(principal: SecurityPrincipal) -> None:
    if not has_permission(principal.actor(), Permission.READ_OPERATIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="permission denied")


def _factory(session: Session) -> tuple[Engine, sessionmaker[Session]]:
    engine = session.get_bind()
    if not isinstance(engine, Engine):
        raise TypeError("workflow API requires an engine-backed session")
    return engine, create_session_factory(engine)


@contextmanager
def _workflow_service(session: Session) -> Iterator[CustomerIssueWorkflow]:
    engine, factory = _factory(session)
    lifecycle = WorkflowLifecycleStore(factory)
    if engine.dialect.name == "postgresql":
        database_url = engine.url.render_as_string(hide_password=False)
        with open_postgres_checkpointer(database_url) as postgres_saver:
            yield _build_workflow(factory, lifecycle, postgres_saver)
        return
    with _checkpointer_lock:
        memory_saver = _sqlite_checkpointers.setdefault(
            id(engine), InMemorySaver(serde=checkpoint_serializer())
        )
    yield _build_workflow(factory, lifecycle, memory_saver)


def _build_workflow(
    factory: sessionmaker[Session],
    lifecycle: WorkflowLifecycleStore,
    saver: BaseCheckpointSaver[Any],
) -> CustomerIssueWorkflow:
    return CustomerIssueWorkflow(
        factory,
        FeatureHashEmbeddingProvider(dimensions=128),
        checkpointer=saver,
        lifecycle_store=lifecycle,
    )


def _lifecycle(session: Session) -> WorkflowLifecycleStore:
    _engine, factory = _factory(session)
    return WorkflowLifecycleStore(factory)


@router.post("/cases", response_model=Case, status_code=status.HTTP_201_CREATED)
def submit_complaint(
    body: ComplaintSubmission, session: DatabaseSession, principal: Principal
) -> Case:
    _require_operations_access(principal)
    try:
        customer_case, _classification = CaseIntakeService(session).submit(
            IntakeRequest(**body.model_dump())
        )
        session.commit()
        return customer_case
    except ValueError as exc:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.get("/cases", response_model=list[Case])
def list_cases(session: DatabaseSession, principal: Principal) -> list[Case]:
    _require_operations_access(principal)
    return CustomerOperationsStore(session).list_cases()


@router.get("/cases/{case_id}", response_model=Case)
def get_case(case_id: str, session: DatabaseSession, principal: Principal) -> Case:
    _require_operations_access(principal)
    customer_case = CustomerOperationsStore(session).get_case(case_id)
    if customer_case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    return customer_case


@router.post(
    "/workflows",
    response_model=WorkflowResult | WorkflowPause,
    status_code=status.HTTP_201_CREATED,
)
def start_workflow(
    body: StartWorkflow, session: DatabaseSession, principal: Principal
) -> WorkflowResult | WorkflowPause:
    _require_operations_access(principal)
    request = WorkflowRequest(actor=principal.actor(), **body.model_dump())
    try:
        with _workflow_service(session) as workflow:
            return workflow.start(request)
    except WorkflowLifecycleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.message) from exc


@router.get("/workflows/{workflow_id}", response_model=WorkflowResult | WorkflowPause)
def get_workflow(
    workflow_id: str, session: DatabaseSession, principal: Principal
) -> WorkflowResult | WorkflowPause:
    _require_operations_access(principal)
    try:
        with _workflow_service(session) as workflow:
            return workflow.get_execution(workflow_id)
    except WorkflowLifecycleError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc


@router.get("/workflows/{workflow_id}/events", response_model=list[WorkflowEvent])
def get_workflow_events(
    workflow_id: str, session: DatabaseSession, principal: Principal
) -> list[WorkflowEvent]:
    _require_operations_access(principal)
    try:
        return _lifecycle(session).list_events(workflow_id)
    except WorkflowLifecycleError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message) from exc


@router.get("/approvals", response_model=list[WorkflowApproval])
def list_approvals(
    session: DatabaseSession,
    principal: Principal,
    approval_status: Annotated[ApprovalStatus | None, Query(alias="status")] = None,
) -> list[WorkflowApproval]:
    _require_operations_access(principal)
    return _lifecycle(session).list_approvals(approval_status=approval_status)


@router.post(
    "/approvals/{approval_id}/decision",
    response_model=WorkflowResult | WorkflowPause,
)
def decide_approval(
    approval_id: str,
    body: ApprovalDecision,
    session: DatabaseSession,
    principal: Principal,
) -> WorkflowResult | WorkflowPause:
    decision = WorkflowApprovalDecision(
        approval_id=approval_id,
        decision=body.decision,
        actor=principal.actor(),
        note=body.note,
    )
    try:
        with _workflow_service(session) as workflow:
            return workflow.resume(decision)
    except ApprovalDecisionError as exc:
        error_status = (
            status.HTTP_403_FORBIDDEN
            if exc.code in {"approval_permission_denied", "permission_denied"}
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=error_status, detail=exc.message) from exc


@router.get("/cases/{case_id}/timeline", response_model=list[CaseTimelineEvent])
def case_timeline(
    case_id: str, session: DatabaseSession, principal: Principal
) -> list[CaseTimelineEvent]:
    _require_operations_access(principal)
    customer_case = CustomerOperationsStore(session).get_case(case_id)
    if customer_case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    events: list[CaseTimelineEvent] = []
    if customer_case.complaint_text is not None:
        events.append(
            CaseTimelineEvent(
                event_id=f"{case_id}-complaint",
                event_type="complaint_received",
                occurred_at=customer_case.opened_at,
                entity_id=case_id,
                details={"complaint": customer_case.complaint_text},
            )
        )
    for issue in customer_case.issues:
        events.append(
            CaseTimelineEvent(
                event_id=f"{issue.issue_id}-reported",
                event_type="issue_classified",
                occurred_at=issue.reported_at,
                entity_id=issue.issue_id,
                details={
                    "issue_type": issue.issue_type.value,
                    "confidence": issue.classification_confidence,
                },
            )
        )
        events.extend(
            CaseTimelineEvent(
                event_id=evidence.evidence_id,
                event_type="evidence_collected",
                occurred_at=evidence.collected_at,
                entity_id=evidence.reference_id,
                details={"source": evidence.source, "summary": evidence.summary},
            )
            for evidence in issue.evidence
        )
        events.extend(
            CaseTimelineEvent(
                event_id=action.action_id,
                event_type=f"action_{action.status.value}",
                occurred_at=action.completed_at or action.created_at,
                entity_id=action.action_id,
                details={"name": action.name},
            )
            for action in issue.actions
        )
        if issue.verification is not None and issue.verification.checked_at is not None:
            events.append(
                CaseTimelineEvent(
                    event_id=f"{issue.issue_id}-verification",
                    event_type=f"verification_{issue.verification.status.value}",
                    occurred_at=issue.verification.checked_at,
                    entity_id=issue.issue_id,
                    details={"summary": issue.verification.summary},
                )
            )
    lifecycle = _lifecycle(session)
    for run in lifecycle.list_runs(case_id=case_id):
        events.extend(
            CaseTimelineEvent(
                event_id=event.event_id,
                event_type=event.event_type.value,
                occurred_at=event.occurred_at,
                entity_id=event.workflow_id,
                details=event.details,
            )
            for event in lifecycle.list_events(run.workflow_id)
        )
    return sorted(events, key=lambda event: (event.occurred_at, event.event_id))
