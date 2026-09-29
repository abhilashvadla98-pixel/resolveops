from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import Field
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from resolveops.api.dependencies import get_principal, get_tenant_session
from resolveops.database.employee_it_records import (
    EmployeeRecord,
    ITAccessCaseRecord,
    ITAccessRequestRecord,
    ITTicketRecord,
)
from resolveops.database.session import create_session_factory
from resolveops.employee_it.models import Employee, EmployeeAccessSnapshot, ITCaseStatus
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
