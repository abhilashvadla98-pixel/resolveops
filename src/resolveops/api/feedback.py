from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import Field
from sqlalchemy.orm import Session

from resolveops.api.dependencies import get_principal, get_tenant_session
from resolveops.database.records import CaseRecord
from resolveops.feedback.models import FeedbackKind, FeedbackReviewStatus, OperatorFeedback
from resolveops.feedback.store import OperatorFeedbackStore
from resolveops.models.common import DomainModel, Identifier, NonEmptyText
from resolveops.operations.auth import has_permission
from resolveops.operations.models import Permission
from resolveops.security.models import SecurityPrincipal

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])
DatabaseSession = Annotated[Session, Depends(get_tenant_session)]
Principal = Annotated[SecurityPrincipal, Depends(get_principal)]


class FeedbackSubmission(DomainModel):
    case_id: Identifier
    workflow_id: Identifier | None = None
    trace_id: Identifier | None = None
    kind: FeedbackKind
    original_value: dict[str, object]
    corrected_value: dict[str, object]
    reason: NonEmptyText
    model_provider: str | None = Field(default=None, max_length=100)
    model_name: str | None = Field(default=None, max_length=200)
    prompt_version: str | None = Field(default=None, max_length=100)


class FeedbackReview(DomainModel):
    status: FeedbackReviewStatus
    note: NonEmptyText


def _require_access(principal: SecurityPrincipal) -> None:
    if not has_permission(principal.actor(), Permission.READ_OPERATIONS):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="permission denied")


@router.post("", response_model=OperatorFeedback, status_code=status.HTTP_201_CREATED)
def submit_feedback(
    body: FeedbackSubmission, session: DatabaseSession, principal: Principal
) -> OperatorFeedback:
    _require_access(principal)
    if session.get(CaseRecord, body.case_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="case not found")
    operator_id = (
        "DEMO-OPERATOR"
        if principal.authentication_method == "demo_session"
        else principal.subject_id
    )
    feedback = OperatorFeedbackStore(session).create(operator_id=operator_id, **body.model_dump())
    session.commit()
    return feedback


@router.get("", response_model=list[OperatorFeedback])
def list_feedback(
    session: DatabaseSession,
    principal: Principal,
    case_id: str | None = None,
    review_status: Annotated[FeedbackReviewStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[OperatorFeedback]:
    _require_access(principal)
    return OperatorFeedbackStore(session).list(
        case_id=case_id, review_status=review_status, limit=limit
    )


@router.post("/{feedback_id}/review", response_model=OperatorFeedback)
def review_feedback(
    feedback_id: str, body: FeedbackReview, session: DatabaseSession, principal: Principal
) -> OperatorFeedback:
    _require_access(principal)
    reviewer_id = (
        "DEMO-APPROVER"
        if principal.authentication_method == "demo_session"
        else principal.subject_id
    )
    try:
        feedback = OperatorFeedbackStore(session).review(
            feedback_id, status=body.status, reviewer_id=reviewer_id, note=body.note
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if feedback is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="feedback not found")
    session.commit()
    return feedback
