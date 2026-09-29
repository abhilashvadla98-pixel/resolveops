from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from resolveops.database.base import Base
from resolveops.database.records import UTCDateTime, enum_type
from resolveops.feedback.models import FeedbackKind, FeedbackReviewStatus


class OperatorFeedbackRecord(Base):
    __tablename__ = "operator_feedback"
    __table_args__ = (
        CheckConstraint(
            "(review_status = 'pending' AND reviewed_by IS NULL AND reviewed_at IS NULL) OR "
            "(review_status != 'pending' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="ck_operator_feedback_review_state",
        ),
        CheckConstraint(
            "review_status != 'promoted' OR dataset_example_id IS NOT NULL",
            name="ck_operator_feedback_promoted_example",
        ),
    )

    feedback_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    workflow_id: Mapped[str | None] = mapped_column(String(100), index=True)
    trace_id: Mapped[str | None] = mapped_column(String(100), index=True)
    kind: Mapped[FeedbackKind] = mapped_column(enum_type(FeedbackKind, "feedback_kind"))
    original_value: Mapped[dict[str, object]] = mapped_column(JSON)
    corrected_value: Mapped[dict[str, object]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    operator_id: Mapped[str] = mapped_column(String(100), index=True)
    model_provider: Mapped[str | None] = mapped_column(String(100))
    model_name: Mapped[str | None] = mapped_column(String(200))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    review_status: Mapped[FeedbackReviewStatus] = mapped_column(
        enum_type(FeedbackReviewStatus, "feedback_review_status"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    review_note: Mapped[str | None] = mapped_column(Text)
    dataset_example_id: Mapped[str | None] = mapped_column(String(100), unique=True)
