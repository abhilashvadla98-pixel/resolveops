from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from resolveops.database.base import Base
from resolveops.database.records import UTCDateTime, enum_type
from resolveops.memory.models import MemoryReviewStatus


class ReviewedResolutionMemoryRecord(Base):
    __tablename__ = "reviewed_resolution_memory"
    __table_args__ = (
        CheckConstraint("expires_at > created_at", name="ck_reviewed_memory_expiry"),
        Index(
            "ix_reviewed_memory_tenant_issue_expiry",
            "tenant_id",
            "issue_type",
            "expires_at",
        ),
    )

    memory_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(100), index=True)
    issue_type: Mapped[str] = mapped_column(String(100))
    evidence_pattern: Mapped[list[str]] = mapped_column(JSON)
    policy_versions: Mapped[dict[str, int]] = mapped_column(JSON)
    approved_resolution: Mapped[dict[str, object]] = mapped_column(JSON)
    verification_outcome: Mapped[str] = mapped_column(String(1000))
    human_feedback_id: Mapped[str | None] = mapped_column(String(100))
    review_status: Mapped[MemoryReviewStatus] = mapped_column(
        enum_type(MemoryReviewStatus, "memory_review_status")
    )
    reviewed_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
