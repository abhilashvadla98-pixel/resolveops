from datetime import UTC, datetime
from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import Field
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from resolveops.api.dependencies import get_principal, get_tenant_session
from resolveops.database.employee_it_records import (
    EmployeeRecord,
    GitRepositoryRecord,
    ITAccessApprovalDecisionRecord,
    ITAccessCaseRecord,
    ITAccessRequestRecord,
    ITTicketRecord,
    TeamRecord,
)
from resolveops.database.session import create_session_factory
from resolveops.employee_it.models import (
    AccessRequestStatus,
    Employee,
    EmployeeAccessSnapshot,
    ITCaseStatus,
)
from resolveops.employee_it.store import EmployeeITStore
from resolveops.employee_it.workflow import EmployeeAccessWorkflow
from resolveops.employee_it.workflow_models import (
    EmployeeAccessWorkflowRequest,
    EmployeeAccessWorkflowResult,
)
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.models.common import AwareDatetime, DomainModel, Identifier, NonEmptyText
from resolveops.operations.auth import has_permission
from resolveops.operations.errors import ResourceNotFoundError
from resolveops.operations.models import Actor, ActorRole, Permission
from resolveops.security.models import SecurityPrincipal
from resolveops.security.pii import redact_employee, redact_employee_access_snapshot
from resolveops.workflows.models import ApprovalDecisionType, ApprovalStatus

router = APIRouter(prefix="/simulator/v1/it", tags=["employee and IT simulator"])
action_router = APIRouter(prefix="/api/v1/it", tags=["employee and IT operations"])
DatabaseSession = Annotated[Session, Depends(get_tenant_session)]
Principal = Annotated[SecurityPrincipal, Depends(get_principal)]


class ITRequestQueueItem(DomainModel):
    case_id: Identifier
    employee_id: Identifier
    employee_name: NonEmptyText
    request_id: Identifier
    request_status: str
    case_status: str
    requested_level: str
    ticket_status: str
    updated_at: AwareDatetime


class ITRequestQueuePage(DomainModel):
    items: list[ITRequestQueueItem]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)


class ITApprovalDecision(DomainModel):
    decision: ApprovalDecisionType
    note: NonEmptyText


class ITApprovalItem(DomainModel):
    approval_id: Identifier
    case_id: Identifier
    access_request_id: Identifier
    employee_id: Identifier
    employee_name: NonEmptyText
    repository_name: NonEmptyText
    requested_level: str
    manager_employee_id: Identifier
    status: ApprovalStatus
    requested_at: AwareDatetime
    decided_by: Identifier | None = None
    decision_note: str | None = None
    decided_at: AwareDatetime | None = None


def workflow_actor(principal: SecurityPrincipal) -> Actor:
    if principal.authentication_method == "demo_session":
        return Actor(actor_id="DEMO-IT-OPERATOR", role=ActorRole.OPERATOR)
    return principal.actor()


def not_found(resource: str, resource_id: str) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{resource} {resource_id} was not found",
    )


@router.get("/employees/{employee_id}", response_model=Employee)
def read_employee(employee_id: str, session: DatabaseSession, principal: Principal) -> Employee:
    employee = EmployeeITStore(session).get_employee(employee_id)
    if employee is None:
        not_found("employee", employee_id)
    return (
        employee
        if has_permission(principal.actor(), Permission.READ_PII)
        else redact_employee(employee)
    )


@router.get("/cases/{case_id}", response_model=EmployeeAccessSnapshot)
def read_access_case(
    case_id: str, session: DatabaseSession, principal: Principal
) -> EmployeeAccessSnapshot:
    try:
        snapshot = EmployeeITStore(session).get_snapshot(case_id)
    except ResourceNotFoundError:
        not_found("IT access case", case_id)
    return (
        snapshot
        if has_permission(principal.actor(), Permission.READ_PII)
        else redact_employee_access_snapshot(snapshot)
    )


@action_router.get("/cases", response_model=ITRequestQueuePage)
def list_access_cases(
    session: DatabaseSession,
    principal: Principal,
    case_status: Annotated[ITCaseStatus | None, Query(alias="status")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
) -> ITRequestQueuePage:
    if not has_permission(principal.actor(), Permission.READ_OPERATIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="permission denied")
    filters = [ITAccessCaseRecord.status == case_status] if case_status is not None else []
    statement = (
        select(ITAccessCaseRecord, ITAccessRequestRecord, EmployeeRecord, ITTicketRecord)
        .join(ITAccessRequestRecord, ITAccessRequestRecord.case_id == ITAccessCaseRecord.case_id)
        .join(EmployeeRecord, EmployeeRecord.employee_id == ITAccessCaseRecord.employee_id)
        .join(ITTicketRecord, ITTicketRecord.case_id == ITAccessCaseRecord.case_id)
    )
    count_statement = select(func.count()).select_from(ITAccessCaseRecord)
    if filters:
        statement = statement.where(*filters)
        count_statement = count_statement.where(*filters)
    may_read_pii = has_permission(principal.actor(), Permission.READ_PII)
    rows = session.execute(
        statement.order_by(ITAccessCaseRecord.updated_at.desc(), ITAccessCaseRecord.case_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ITRequestQueuePage(
        items=[
            ITRequestQueueItem(
                case_id=case.case_id,
                employee_id=case.employee_id,
                employee_name=employee.name if may_read_pii else "Restricted employee",
                request_id=request.access_request_id,
                request_status=request.status.value,
                case_status=case.status.value,
                requested_level=request.requested_level.value,
                ticket_status=ticket.status.value,
                updated_at=case.updated_at,
            )
            for case, request, employee, ticket in rows
        ],
        page=page,
        page_size=page_size,
        total=session.scalar(count_statement) or 0,
    )


def _approval_item(
    request: ITAccessRequestRecord,
    employee: EmployeeRecord,
    repository: GitRepositoryRecord,
    team: TeamRecord,
    *,
    may_read_pii: bool,
    decision: ITAccessApprovalDecisionRecord | None = None,
) -> ITApprovalItem:
    status_value = (
        ApprovalStatus.PENDING
        if decision is None
        else ApprovalStatus.APPROVED
        if decision.decision == ApprovalDecisionType.APPROVE
        else ApprovalStatus.REJECTED
    )
    return ITApprovalItem(
        approval_id=f"IT-APPROVAL-{request.case_id}",
        case_id=request.case_id,
        access_request_id=request.access_request_id,
        employee_id=request.employee_id,
        employee_name=employee.name if may_read_pii else "Restricted employee",
        repository_name=repository.name,
        requested_level=request.requested_level.value,
        manager_employee_id=team.manager_employee_id,
        status=status_value,
        requested_at=request.requested_at,
        decided_by=decision.decided_by if decision else None,
        decision_note=decision.note if decision else None,
        decided_at=decision.decided_at if decision else None,
    )


@action_router.get("/approvals", response_model=list[ITApprovalItem])
def list_access_approvals(
    session: DatabaseSession,
    principal: Principal,
    approval_status: Annotated[ApprovalStatus | None, Query(alias="status")] = None,
) -> list[ITApprovalItem]:
    if not has_permission(principal.actor(), Permission.READ_OPERATIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="permission denied")
    may_read_pii = has_permission(principal.actor(), Permission.READ_PII)
    base = (
        select(ITAccessRequestRecord, EmployeeRecord, GitRepositoryRecord, TeamRecord)
        .join(EmployeeRecord, EmployeeRecord.employee_id == ITAccessRequestRecord.employee_id)
        .join(
            GitRepositoryRecord,
            GitRepositoryRecord.repository_id == ITAccessRequestRecord.repository_id,
        )
        .join(TeamRecord, TeamRecord.team_id == ITAccessRequestRecord.target_team_id)
    )
    items: list[ITApprovalItem] = []
    if approval_status in {None, ApprovalStatus.PENDING}:
        pending = session.execute(
            base.where(ITAccessRequestRecord.status == AccessRequestStatus.PENDING_APPROVAL)
        ).all()
        items.extend(
            _approval_item(request, employee, repository, team, may_read_pii=may_read_pii)
            for request, employee, repository, team in pending
        )
    if approval_status != ApprovalStatus.PENDING:
        decision_statement = select(ITAccessApprovalDecisionRecord)
        if approval_status is not None:
            decision_statement = decision_statement.where(
                ITAccessApprovalDecisionRecord.decision
                == (
                    ApprovalDecisionType.APPROVE
                    if approval_status == ApprovalStatus.APPROVED
                    else ApprovalDecisionType.REJECT
                )
            )
        for decision in session.scalars(decision_statement):
            request = session.get(ITAccessRequestRecord, decision.access_request_id)
            if request is None:
                continue
            employee = session.get(EmployeeRecord, request.employee_id)
            repository = session.get(GitRepositoryRecord, request.repository_id)
            team = session.get(TeamRecord, request.target_team_id)
            if employee is None or repository is None or team is None:
                continue
            items.append(
                _approval_item(
                    request,
                    employee,
                    repository,
                    team,
                    may_read_pii=may_read_pii,
                    decision=decision,
                )
            )
    return sorted(items, key=lambda item: (item.requested_at, item.approval_id), reverse=True)


@action_router.post("/approvals/{case_id}/decision", response_model=ITApprovalItem)
def decide_access_approval(
    case_id: str,
    body: ITApprovalDecision,
    session: DatabaseSession,
    principal: Principal,
) -> ITApprovalItem:
    is_demo = principal.authentication_method == "demo_session"
    if not is_demo and principal.role not in {ActorRole.APPROVER, ActorRole.SYSTEM}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="approver role required")
    try:
        snapshot = EmployeeITStore(session).get_snapshot(case_id)
    except ResourceNotFoundError:
        not_found("IT access case", case_id)
    request = session.get(ITAccessRequestRecord, snapshot.access_request.access_request_id)
    access_case = session.get(ITAccessCaseRecord, case_id)
    employee = session.get(EmployeeRecord, snapshot.employee.employee_id)
    repository = session.get(GitRepositoryRecord, snapshot.repository.repository_id)
    team = session.get(TeamRecord, snapshot.team.team_id)
    if any(item is None for item in (request, access_case, employee, repository, team)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="IT approval data is incomplete"
        )
    assert request is not None and access_case is not None
    assert employee is not None and repository is not None and team is not None
    existing = session.scalar(
        select(ITAccessApprovalDecisionRecord).where(
            ITAccessApprovalDecisionRecord.case_id == case_id
        )
    )
    if existing is not None:
        if existing.decision != body.decision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="IT approval already has a different decision",
            )
        return _approval_item(
            request,
            employee,
            repository,
            team,
            may_read_pii=has_permission(principal.actor(), Permission.READ_PII),
            decision=existing,
        )
    if request.status != AccessRequestStatus.PENDING_APPROVAL:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="IT request is not waiting for approval",
        )
    now = datetime.now(UTC)
    decided_by = "DEMO-APPROVER" if is_demo else principal.subject_id
    decision = ITAccessApprovalDecisionRecord(
        approval_id=f"IT-APPROVAL-{case_id}",
        case_id=case_id,
        access_request_id=request.access_request_id,
        decision=body.decision,
        decided_by=decided_by,
        manager_employee_id=team.manager_employee_id,
        note=body.note,
        decided_at=now,
    )
    if body.decision == ApprovalDecisionType.APPROVE:
        request.status = AccessRequestStatus.APPROVED
        request.approved_by = team.manager_employee_id
        request.approved_at = now
        access_case.status = ITCaseStatus.ACTION_PENDING
    else:
        request.status = AccessRequestStatus.REJECTED
        access_case.status = ITCaseStatus.ESCALATED
    access_case.updated_at = now
    session.add(decision)
    session.commit()
    return _approval_item(
        request,
        employee,
        repository,
        team,
        may_read_pii=has_permission(principal.actor(), Permission.READ_PII),
        decision=decision,
    )


@action_router.post(
    "/cases/{case_id}/execute",
    response_model=EmployeeAccessWorkflowResult,
)
def execute_access_case(
    case_id: str, session: DatabaseSession, principal: Principal
) -> EmployeeAccessWorkflowResult:
    if not has_permission(principal.actor(), Permission.READ_OPERATIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="permission denied")
    engine = session.get_bind()
    if not isinstance(engine, Engine):
        raise TypeError("employee workflow API requires an engine-backed session")
    try:
        EmployeeITStore(session).get_snapshot(case_id)
    except ResourceNotFoundError:
        not_found("IT access case", case_id)
    workflow = EmployeeAccessWorkflow(
        create_session_factory(engine),
        FeatureHashEmbeddingProvider(dimensions=128),
    )
    return workflow.run(
        EmployeeAccessWorkflowRequest(
            workflow_id=f"IT-WORKFLOW-{case_id}",
            case_id=case_id,
            actor=workflow_actor(principal),
        )
    )
