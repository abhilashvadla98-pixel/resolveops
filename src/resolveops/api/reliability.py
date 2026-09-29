from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from resolveops.api.dependencies import get_principal, get_tenant_session
from resolveops.database.action_records import OperationRecord
from resolveops.models.common import AwareDatetime, DomainModel, Identifier
from resolveops.operations.auth import has_permission
from resolveops.operations.models import (
    OperationStatus,
    OperationType,
    Permission,
    ReliabilityEvent,
    ReliabilityEventType,
)
from resolveops.security.models import SecurityPrincipal

router = APIRouter(prefix="/api/v1/reliability", tags=["reliability"])
DatabaseSession = Annotated[Session, Depends(get_tenant_session)]
Principal = Annotated[SecurityPrincipal, Depends(get_principal)]


class OperationReliabilityTrace(DomainModel):
    operation_id: Identifier
    operation_type: OperationType
    status: OperationStatus
    case_id: Identifier | None
    issue_id: Identifier | None
    resource_id: Identifier | None
    attempt_count: int = Field(ge=0)
    verification_attempt_count: int = Field(ge=0)
    duration_ms: float = Field(ge=0)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    events: list[ReliabilityEvent]


class ReliabilitySummary(DomainModel):
    total_operations: int = Field(ge=0)
    outcomes: dict[str, int]
    latency_sample_count: int = Field(ge=0)
    p50_latency_ms: float | None = Field(default=None, ge=0)
    p95_latency_ms: float | None = Field(default=None, ge=0)
    failed_operation_count: int = Field(ge=0)
    retry_scheduled_count: int = Field(ge=0)
    wait_scheduled_count: int = Field(ge=0)
    recovery_event_count: int = Field(ge=0)
    manual_review_count: int = Field(ge=0)
    recent_operations: list[OperationReliabilityTrace]


@router.get("/summary", response_model=ReliabilitySummary)
def reliability_summary(session: DatabaseSession, principal: Principal) -> ReliabilitySummary:
    if not has_permission(principal.actor(), Permission.READ_OPERATIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="permission denied")
    records = list(
        session.scalars(
            select(OperationRecord)
            .options(selectinload(OperationRecord.reliability_events))
            .order_by(OperationRecord.updated_at.desc(), OperationRecord.operation_id)
        )
    )
    durations = sorted(
        max((record.updated_at - record.created_at).total_seconds() * 1000, 0) for record in records
    )
    all_events = [event for record in records for event in record.reliability_events]
    retry_types = {
        ReliabilityEventType.RETRY_SCHEDULED,
        ReliabilityEventType.VERIFICATION_RETRY_SCHEDULED,
    }
    recovery_types = {
        ReliabilityEventType.LEASE_RECOVERED,
        ReliabilityEventType.RECOVERY_VERIFIED,
    }
    failed_statuses = {OperationStatus.FAILED, OperationStatus.VERIFICATION_FAILED}
    return ReliabilitySummary(
        total_operations=len(records),
        outcomes=dict(sorted(Counter(record.status.value for record in records).items())),
        latency_sample_count=len(durations),
        p50_latency_ms=_nearest_rank(durations, 0.50),
        p95_latency_ms=_nearest_rank(durations, 0.95),
        failed_operation_count=sum(record.status in failed_statuses for record in records),
        retry_scheduled_count=sum(event.event_type in retry_types for event in all_events),
        wait_scheduled_count=sum(event.event_type in retry_types for event in all_events),
        recovery_event_count=sum(event.event_type in recovery_types for event in all_events),
        manual_review_count=sum(
            event.event_type == ReliabilityEventType.MANUAL_REVIEW_REQUIRED for event in all_events
        ),
        recent_operations=[_trace(record) for record in records[:20]],
    )


def _nearest_rank(ordered: list[float], percentile: float) -> float | None:
    if not ordered:
        return None
    rank = max(int(len(ordered) * percentile + 0.999999) - 1, 0)
    return round(ordered[rank], 3)


def _trace(record: OperationRecord) -> OperationReliabilityTrace:
    return OperationReliabilityTrace(
        operation_id=record.operation_id,
        operation_type=record.operation_type,
        status=record.status,
        case_id=record.case_id,
        issue_id=record.issue_id,
        resource_id=record.result_resource_id,
        attempt_count=record.attempt_count,
        verification_attempt_count=record.verification_attempt_count,
        duration_ms=round(
            max((record.updated_at - record.created_at).total_seconds() * 1000, 0), 3
        ),
        created_at=record.created_at,
        updated_at=record.updated_at,
        events=[
            ReliabilityEvent(
                reliability_event_id=event.reliability_event_id,
                operation_id=event.operation_id,
                sequence_number=event.sequence_number,
                event_type=event.event_type,
                attempt_number=event.attempt_number,
                details=event.details,
                occurred_at=event.occurred_at,
            )
            for event in record.reliability_events
        ],
    )
