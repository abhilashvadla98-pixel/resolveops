from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from resolveops.api.dependencies import get_principal, get_tenant_session
from resolveops.database.action_records import AuditEventRecord
from resolveops.database.employee_it_records import (
    ITAccessApprovalDecisionRecord,
    ITWorkflowExecutionRecord,
)
from resolveops.database.workflow_records import WorkflowEventRecord, WorkflowRunRecord
from resolveops.models.common import AwareDatetime, DomainModel, Identifier
from resolveops.operations.auth import has_permission
from resolveops.operations.models import Permission
from resolveops.security.models import SecurityPrincipal

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])
DatabaseSession = Annotated[Session, Depends(get_tenant_session)]
Principal = Annotated[SecurityPrincipal, Depends(get_principal)]


class GlobalAuditEvent(DomainModel):
    event_id: Identifier
    occurred_at: AwareDatetime
    actor_id: str | None
    case_id: str | None
    workflow_or_operation_id: Identifier
    event_type: str
    result: str | None
    trace_id: str | None


@router.get("/events", response_model=list[GlobalAuditEvent])
def recent_audit_events(
    session: DatabaseSession,
    principal: Principal,
    case_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[GlobalAuditEvent]:
    if not has_permission(principal.actor(), Permission.READ_OPERATIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="permission denied")
    audit_statement = select(AuditEventRecord)
    workflow_statement = select(WorkflowEventRecord, WorkflowRunRecord.case_id).join(
        WorkflowRunRecord, WorkflowRunRecord.workflow_id == WorkflowEventRecord.workflow_id
    )
    it_approval_statement = select(ITAccessApprovalDecisionRecord)
    it_workflow_statement = select(ITWorkflowExecutionRecord)
    if case_id:
        audit_statement = audit_statement.where(AuditEventRecord.case_id == case_id)
        workflow_statement = workflow_statement.where(WorkflowRunRecord.case_id == case_id)
        it_approval_statement = it_approval_statement.where(
            ITAccessApprovalDecisionRecord.case_id == case_id
        )
        it_workflow_statement = it_workflow_statement.where(
            ITWorkflowExecutionRecord.case_id == case_id
        )
    audit = list(
        session.scalars(audit_statement.order_by(AuditEventRecord.occurred_at.desc()).limit(limit))
    )
    workflow = session.execute(
        workflow_statement.order_by(WorkflowEventRecord.occurred_at.desc()).limit(limit)
    ).all()
    it_approvals = list(
        session.scalars(
            it_approval_statement.order_by(ITAccessApprovalDecisionRecord.decided_at.desc()).limit(
                limit
            )
        )
    )
    it_workflows = list(
        session.scalars(
            it_workflow_statement.order_by(ITWorkflowExecutionRecord.completed_at.desc()).limit(
                limit
            )
        )
    )
    events = [
        GlobalAuditEvent(
            event_id=item.audit_event_id,
            occurred_at=item.occurred_at,
            actor_id=item.actor_id,
            case_id=item.case_id,
            workflow_or_operation_id=item.operation_id,
            event_type=item.event_type.value,
            result=str(item.details.get("result"))
            if item.details.get("result") is not None
            else None,
            trace_id=None,
        )
        for item in audit
    ]
    events.extend(
        GlobalAuditEvent(
            event_id=item.event_id,
            occurred_at=item.occurred_at,
            actor_id=item.actor_id,
            case_id=workflow_case_id,
            workflow_or_operation_id=item.workflow_id,
            event_type=item.event_type.value,
            result=str(item.details.get("outcome"))
            if item.details.get("outcome") is not None
            else None,
            trace_id=str(item.details.get("trace_id"))
            if item.details.get("trace_id") is not None
            else None,
        )
        for item, workflow_case_id in workflow
    )
    events.extend(
        GlobalAuditEvent(
            event_id=f"{item.approval_id}-decision",
            occurred_at=item.decided_at,
            actor_id=item.decided_by,
            case_id=item.case_id,
            workflow_or_operation_id=item.approval_id,
            event_type=(
                "approval_approved" if item.decision.value == "approve" else "approval_rejected"
            ),
            result=item.decision.value,
            trace_id=None,
        )
        for item in it_approvals
    )
    events.extend(
        GlobalAuditEvent(
            event_id=f"{item.workflow_id}-terminal",
            occurred_at=item.completed_at,
            actor_id=None,
            case_id=item.case_id,
            workflow_or_operation_id=item.workflow_id,
            event_type=f"it_workflow_{item.status.value}",
            result=item.outcome.value,
            trace_id=None,
        )
        for item in it_workflows
    )
    return sorted(events, key=lambda item: (item.occurred_at, item.event_id), reverse=True)[:limit]
