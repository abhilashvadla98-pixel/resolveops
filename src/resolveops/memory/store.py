from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from resolveops.database.memory_records import ReviewedResolutionMemoryRecord
from resolveops.memory.models import (
    ApprovedResolutionPattern,
    MemoryReviewStatus,
    ReviewedResolutionMemory,
)


class ReviewedResolutionMemoryStore:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.clock = clock or (lambda: datetime.now(UTC))

    def promote(
        self,
        *,
        tenant_id: str,
        issue_type: str,
        evidence_pattern: list[str],
        policy_versions: dict[str, int],
        approved_resolution: dict[str, object],
        verification_outcome: str,
        reviewed_by: str,
        human_feedback_id: str | None = None,
        ttl_days: int = 90,
    ) -> ReviewedResolutionMemory:
        if not 1 <= ttl_days <= 365:
            raise ValueError("memory TTL must be between 1 and 365 days")
        created_at = self.clock()
        memory = ReviewedResolutionMemory(
            memory_id=f"MEM-{uuid4().hex[:20]}",
            tenant_id=tenant_id,
            issue_type=issue_type,
            evidence_pattern=evidence_pattern,
            policy_versions=policy_versions,
            approved_resolution=ApprovedResolutionPattern.model_validate(approved_resolution),
            verification_outcome=verification_outcome,
            human_feedback_id=human_feedback_id,
            review_status=MemoryReviewStatus.REVIEWED,
            reviewed_by=reviewed_by,
            created_at=created_at,
            expires_at=created_at + timedelta(days=ttl_days),
        )
        with self.session_factory.begin() as session:
            session.add(ReviewedResolutionMemoryRecord(**memory.model_dump()))
        return memory

    def retrieve(
        self,
        *,
        tenant_id: str,
        issue_type: str,
        limit: int = 5,
    ) -> list[ReviewedResolutionMemory]:
        if not 1 <= limit <= 20:
            raise ValueError("memory retrieval limit must be between 1 and 20")
        with self.session_factory() as session:
            records = session.scalars(
                select(ReviewedResolutionMemoryRecord)
                .where(
                    ReviewedResolutionMemoryRecord.tenant_id == tenant_id,
                    ReviewedResolutionMemoryRecord.issue_type == issue_type,
                    ReviewedResolutionMemoryRecord.review_status == MemoryReviewStatus.REVIEWED,
                    ReviewedResolutionMemoryRecord.expires_at > self.clock(),
                )
                .order_by(ReviewedResolutionMemoryRecord.created_at.desc())
                .limit(limit)
            ).all()
            return [self._model(record) for record in records]

    @staticmethod
    def _model(record: ReviewedResolutionMemoryRecord) -> ReviewedResolutionMemory:
        return ReviewedResolutionMemory(
            memory_id=record.memory_id,
            tenant_id=record.tenant_id,
            issue_type=record.issue_type,
            evidence_pattern=record.evidence_pattern,
            policy_versions=record.policy_versions,
            approved_resolution=ApprovedResolutionPattern.model_validate(
                record.approved_resolution
            ),
            verification_outcome=record.verification_outcome,
            human_feedback_id=record.human_feedback_id,
            review_status=record.review_status,
            reviewed_by=record.reviewed_by,
            created_at=record.created_at,
            expires_at=record.expires_at,
        )
