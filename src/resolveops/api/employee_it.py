from datetime import UTC, datetime
from typing import Annotated, Literal, NoReturn
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import Field
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from resolveops.api.dependencies import get_principal, get_tenant_session
from resolveops.database.employee_it_records import (
    EmployeeRecord,
    EnterpriseIdentityRecord,
    GitAccountRecord,
    GitRepositoryRecord,
    ITAccessApprovalDecisionRecord,
    ITAccessCaseRecord,
    ITAccessRequestRecord,
    ITTicketRecord,
    ITWorkflowExecutionRecord,
    TeamRecord,
)
from resolveops.database.session import create_session_factory
from resolveops.employee_it.identity import authenticated_employee
from resolveops.employee_it.intake import EmployeeRequestSubmission, submit_access_request
from resolveops.employee_it.models import (
    AccessRequestStatus,
    Employee,
    EmployeeAccessSnapshot,
    EmploymentStatus,
    IdentityStatus,
    ITCaseStatus,
    RepositoryAccessLevel,
)
from resolveops.employee_it.store import EmployeeITStore
from resolveops.employee_it.workflow import EmployeeAccessWorkflow
from resolveops.employee_it.workflow_models import (
    EmployeeAccessWorkflowRequest,
    EmployeeAccessWorkflowResult,
    EmployeeWorkflowDecision,
    EmployeeWorkflowOutcome,
)
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.models.common import AwareDatetime, DomainModel, Identifier, NonEmptyText
from resolveops.operations.auth import has_permission
from resolveops.operations.errors import (
    AuthorizationError,
    BusinessRuleError,
    ResourceNotFoundError,
)
from resolveops.operations.models import Actor, ActorRole, Permission
from resolveops.security.models import SecurityPrincipal
from resolveops.security.pii import redact_employee, redact_employee_access_snapshot
from resolveops.workflows.models import ApprovalDecisionType, ApprovalStatus, WorkflowStatus

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
    decision_mode: Literal["authenticated_manager", "demo_manager_simulation"] | None = None


class ITEmployeeOption(DomainModel):
    employee_id: Identifier
    name: NonEmptyText


class ITRepositoryOption(DomainModel):
    repository_id: Identifier
    name: NonEmptyText


class ITRequestOptions(DomainModel):
    execution_mode: Literal["deterministic"] = "deterministic"
    demo_personas_enabled: bool
    employees: list[ITEmployeeOption]
    repositories: list[ITRepositoryOption]
    allowed_levels: list[RepositoryAccessLevel]


class ITWorkflowSummary(DomainModel):
    workflow_id: Identifier
    case_id: Identifier
    status: WorkflowStatus
    outcome: EmployeeWorkflowOutcome
    decision: EmployeeWorkflowDecision
    verified_access_id: Identifier | None = None
    resolution_summary: NonEmptyText
    error_code: Identifier | None = None
    error_message: NonEmptyText | None = None
    node_history: list[Identifier]
    created_at: AwareDatetime
    completed_at: AwareDatetime


def workflow_actor(principal: SecurityPrincipal) -> Actor:
    if principal.authentication_method == "demo_session":
        return Actor(actor_id="DEMO-IT-OPERATOR", role=ActorRole.OPERATOR)
    return principal.actor()


def not_found(resource: str, resource_id: str) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"{resource} {resource_id} was not found",
    )


def _employee_identity(
    session: Session, principal: SecurityPrincipal, *, require_mfa: bool = False
) -> tuple[EmployeeRecord, EnterpriseIdentityRecord]:
    try:
        return authenticated_employee(session, principal.subject_id, require_mfa=require_mfa)
    except AuthorizationError as exc:
        raise HTTPException(status_code=403, detail=exc.message) from exc


@action_router.get("/request-options", response_model=ITRequestOptions)
def request_options(session: DatabaseSession, principal: Principal) -> ITRequestOptions:
    if not has_permission(principal.actor(), Permission.READ_OPERATIONS):
        raise HTTPException(status_code=403, detail="permission denied")
    is_demo = principal.authentication_method == "demo_session"
    if is_demo:
        employees = list(
            session.scalars(
                select(EmployeeRecord)
                .join(EnterpriseIdentityRecord)
                .join(
                    GitAccountRecord,
                    GitAccountRecord.identity_id == EnterpriseIdentityRecord.identity_id,
                )
                .where(
                    EmployeeRecord.status == EmploymentStatus.ACTIVE,
                    EnterpriseIdentityRecord.status == IdentityStatus.ACTIVE,
                )
                .order_by(EmployeeRecord.name)
            )
        )
    else:
        employee, _identity = _employee_identity(session, principal)
        employees = [employee]
    return ITRequestOptions(
        demo_personas_enabled=is_demo,
        employees=[
            ITEmployeeOption(employee_id=item.employee_id, name=item.name) for item in employees
        ],
        repositories=[
            ITRepositoryOption(repository_id=item.repository_id, name=item.name)
            for item in session.scalars(
                select(GitRepositoryRecord).order_by(GitRepositoryRecord.name)
            )
        ],
        allowed_levels=[RepositoryAccessLevel.READ, RepositoryAccessLevel.WRITE],
    )


@action_router.post("/requests", response_model=EmployeeAccessSnapshot, status_code=201)
def create_access_request(
    body: EmployeeRequestSubmission, session: DatabaseSession, principal: Principal
) -> EmployeeAccessSnapshot:
    if not has_permission(principal.actor(), Permission.READ_OPERATIONS):
        raise HTTPException(status_code=403, detail="permission denied")
    is_demo = principal.authentication_method == "demo_session"
    if is_demo:
        identity = session.scalar(
            select(EnterpriseIdentityRecord).where(
                EnterpriseIdentityRecord.employee_id == body.demo_employee_id
            )
        )
        if identity is None:
            raise HTTPException(status_code=422, detail="Choose an existing demo employee.")
        try:
            employee, identity = authenticated_employee(session, identity.identity_id)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=exc.message) from exc
    else:
        if body.demo_employee_id is not None:
            raise HTTPException(
                status_code=403, detail="Demo personas are unavailable in this session."
            )
        employee, identity = _employee_identity(session, principal)
    try:
        result = submit_access_request(session, body, employee, identity)
        session.commit()
    except IntegrityError:
        session.rollback()
        try:
            result = submit_access_request(session, body, employee, identity)
            session.commit()
        except BusinessRuleError as exc:
            session.rollback()
            raise HTTPException(status_code=409, detail=exc.message) from exc
    except BusinessRuleError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail=exc.message) from exc
    return (
        result
        if has_permission(principal.actor(), Permission.READ_PII)
        else redact_employee_access_snapshot(result)
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
        decision_mode=(
            "demo_manager_simulation"
            if decision is not None and decision.decided_by.startswith("DEMO-MANAGER:")
            else "authenticated_manager"
            if decision is not None
            else None
        ),
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
    request = session.get(
        ITAccessRequestRecord, snapshot.access_request.access_request_id, with_for_update=True
    )
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
    if is_demo:
        manager = session.get(EmployeeRecord, team.manager_employee_id)
        if manager is None or manager.status != EmploymentStatus.ACTIVE:
            raise HTTPException(status_code=403, detail="An active demo manager is required.")
        approver_employee_id = manager.employee_id
        decided_by = f"DEMO-MANAGER:{manager.employee_id}"
    else:
        approver, _identity = _employee_identity(session, principal, require_mfa=True)
        if approver.employee_id != team.manager_employee_id:
            raise HTTPException(
                status_code=403,
                detail="Only the current target-team manager may decide this request.",
            )
        approver_employee_id = approver.employee_id
        decided_by = principal.subject_id
    if approver_employee_id == request.employee_id:
        raise HTTPException(status_code=403, detail="Self-approval is not permitted.")
    existing = session.scalar(
        select(ITAccessApprovalDecisionRecord).where(
            ITAccessApprovalDecisionRecord.case_id == case_id
        )
    )
    if existing is not None:
        if (
            existing.decision != body.decision
            or existing.decided_by != decided_by
            or existing.note != body.note
        ):
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
        request.approved_by = approver_employee_id
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
    started_at = datetime.now(UTC)
    result = workflow.run(
        EmployeeAccessWorkflowRequest(
            workflow_id=f"IT-WF-{uuid4().hex}",
            case_id=case_id,
            actor=workflow_actor(principal),
        )
    )
    session.add(
        ITWorkflowExecutionRecord(
            workflow_id=result.workflow_id,
            case_id=result.case_id,
            status=result.status,
            outcome=result.outcome,
            decision=result.decision,
            verified_access_id=result.verified_access_id,
            resolution_summary=result.resolution_summary,
            error_code=result.error_code,
            error_message=result.error_message,
            node_history=result.node_history,
            created_at=started_at,
            completed_at=datetime.now(UTC),
        )
    )
    if result.status == WorkflowStatus.ESCALATED:
        access_case = session.get(ITAccessCaseRecord, case_id)
        if access_case is not None:
            access_case.status = ITCaseStatus.ESCALATED
            access_case.updated_at = datetime.now(UTC)
    session.commit()
    return result


@action_router.get("/cases/{case_id}/workflow", response_model=ITWorkflowSummary)
def get_access_workflow(
    case_id: str, session: DatabaseSession, principal: Principal
) -> ITWorkflowSummary:
    if not has_permission(principal.actor(), Permission.READ_OPERATIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="permission denied")
    record = session.scalar(
        select(ITWorkflowExecutionRecord)
        .where(ITWorkflowExecutionRecord.case_id == case_id)
        .order_by(
            ITWorkflowExecutionRecord.created_at.desc(),
            ITWorkflowExecutionRecord.workflow_id.desc(),
        )
        .limit(1)
    )
    if record is None:
        not_found("IT workflow for case", case_id)
    return _workflow_summary(record)


@action_router.get("/cases/{case_id}/workflows", response_model=list[ITWorkflowSummary])
def list_access_workflows(
    case_id: str, session: DatabaseSession, principal: Principal
) -> list[ITWorkflowSummary]:
    if not has_permission(principal.actor(), Permission.READ_OPERATIONS):
        raise HTTPException(status_code=403, detail="permission denied")
    if session.get(ITAccessCaseRecord, case_id) is None:
        not_found("IT access case", case_id)
    return [
        _workflow_summary(record)
        for record in session.scalars(
            select(ITWorkflowExecutionRecord)
            .where(ITWorkflowExecutionRecord.case_id == case_id)
            .order_by(
                ITWorkflowExecutionRecord.created_at.desc(),
                ITWorkflowExecutionRecord.workflow_id.desc(),
            )
        )
    ]


def _workflow_summary(record: ITWorkflowExecutionRecord) -> ITWorkflowSummary:
    return ITWorkflowSummary(
        workflow_id=record.workflow_id,
        case_id=record.case_id,
        status=record.status,
        outcome=record.outcome,
        decision=record.decision,
        verified_access_id=record.verified_access_id,
        resolution_summary=record.resolution_summary,
        error_code=record.error_code,
        error_message=record.error_message,
        node_history=record.node_history,
        created_at=record.created_at,
        completed_at=record.completed_at,
    )
