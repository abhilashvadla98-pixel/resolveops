from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from resolveops.api.dependencies import get_principal, get_tenant_session
from resolveops.database.session import create_session_factory
from resolveops.employee_it.models import Employee, EmployeeAccessSnapshot
from resolveops.employee_it.store import EmployeeITStore
from resolveops.employee_it.workflow import EmployeeAccessWorkflow
from resolveops.employee_it.workflow_models import (
    EmployeeAccessWorkflowRequest,
    EmployeeAccessWorkflowResult,
)
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.operations.auth import has_permission
from resolveops.operations.errors import ResourceNotFoundError
from resolveops.operations.models import Actor, ActorRole, Permission
from resolveops.security.models import SecurityPrincipal
from resolveops.security.pii import redact_employee, redact_employee_access_snapshot

router = APIRouter(prefix="/simulator/v1/it", tags=["employee and IT simulator"])
action_router = APIRouter(prefix="/api/v1/it", tags=["employee and IT operations"])
DatabaseSession = Annotated[Session, Depends(get_tenant_session)]
Principal = Annotated[SecurityPrincipal, Depends(get_principal)]


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
