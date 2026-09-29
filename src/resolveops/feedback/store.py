from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from resolveops.database.feedback_records import OperatorFeedbackRecord
from resolveops.feedback.models import FeedbackKind, FeedbackReviewStatus, OperatorFeedback


class OperatorFeedbackStore:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        *,
        case_id: str,
        workflow_id: str | None,
        trace_id: str | None,
        kind: FeedbackKind,
        original_value: dict[str, object],
        corrected_value: dict[str, object],
        reason: str,
        operator_id: str,
        model_provider: str | None,
        model_name: str | None,
        prompt_version: str | None,
    ) -> OperatorFeedback:
        record = OperatorFeedbackRecord(
            feedback_id=f"FDBK-{uuid4().hex[:20]}",
            case_id=case_id,
            workflow_id=workflow_id,
            trace_id=trace_id,
            kind=kind,
            original_value=original_value,
            corrected_value=corrected_value,
            reason=reason,
            operator_id=operator_id,
            model_provider=model_provider,
            model_name=model_name,
            prompt_version=prompt_version,
            review_status=FeedbackReviewStatus.PENDING,
            created_at=datetime.now(UTC),
            reviewed_by=None,
            reviewed_at=None,
            review_note=None,
            dataset_example_id=None,
        )
        self.session.add(record)
        self.session.flush()
        return self._model(record)

    def list(
        self,
        *,
        case_id: str | None = None,
        review_status: FeedbackReviewStatus | None = None,
        limit: int = 100,
    ) -> list[OperatorFeedback]:
        statement = select(OperatorFeedbackRecord)
        if case_id is not None:
            statement = statement.where(OperatorFeedbackRecord.case_id == case_id)
        if review_status is not None:
            statement = statement.where(OperatorFeedbackRecord.review_status == review_status)
        records = self.session.scalars(
            statement.order_by(OperatorFeedbackRecord.created_at.desc()).limit(limit)
        ).all()
        return [self._model(record) for record in records]

    def review(
        self, feedback_id: str, *, status: FeedbackReviewStatus, reviewer_id: str, note: str
    ) -> OperatorFeedback | None:
        if status not in {FeedbackReviewStatus.REVIEWED, FeedbackReviewStatus.REJECTED}:
            raise ValueError("API review may only mark feedback reviewed or rejected")
        record = self.session.get(OperatorFeedbackRecord, feedback_id)
        if record is None:
            return None
        if record.review_status != FeedbackReviewStatus.PENDING:
            raise ValueError("feedback has already been reviewed")
        record.review_status = status
        record.reviewed_by = reviewer_id
        record.reviewed_at = datetime.now(UTC)
        record.review_note = note
        self.session.flush()
        return self._model(record)

    @staticmethod
    def _model(record: OperatorFeedbackRecord) -> OperatorFeedback:
        return OperatorFeedback(
            feedback_id=record.feedback_id,
            case_id=record.case_id,
            workflow_id=record.workflow_id,
            trace_id=record.trace_id,
            kind=record.kind,
            original_value=record.original_value,
            corrected_value=record.corrected_value,
            reason=record.reason,
            operator_id=record.operator_id,
            model_provider=record.model_provider,
            model_name=record.model_name,
            prompt_version=record.prompt_version,
            review_status=record.review_status,
            created_at=record.created_at,
            reviewed_by=record.reviewed_by,
            reviewed_at=record.reviewed_at,
            review_note=record.review_note,
            dataset_example_id=record.dataset_example_id,
        )
