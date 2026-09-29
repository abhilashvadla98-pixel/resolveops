from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from resolveops.database.base import Base
from resolveops.database.records import UTCDateTime, enum_type
from resolveops.knowledge.models import KnowledgeStatus
from resolveops.models.case import CaseIssueType


class KnowledgeDocumentRecord(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_knowledge_documents_positive_version"),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > effective_at",
            name="ck_knowledge_documents_effective_order",
        ),
        UniqueConstraint("document_id", "version", name="uq_knowledge_documents_version"),
    )

    document_version_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(100), index=True)
    title: Mapped[str] = mapped_column(String(1000))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[KnowledgeStatus] = mapped_column(enum_type(KnowledgeStatus, "knowledge_status"))
    source: Mapped[str] = mapped_column(String(1000))
    source_path: Mapped[str] = mapped_column(String(2000))
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    fingerprint_sha256: Mapped[str] = mapped_column(String(64))
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime())

    issue_type_links: Mapped[list["KnowledgeDocumentIssueTypeRecord"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="KnowledgeDocumentIssueTypeRecord.issue_type",
    )
    chunks: Mapped[list["KnowledgeChunkRecord"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="KnowledgeChunkRecord.chunk_index",
    )


class KnowledgeDocumentIssueTypeRecord(Base):
    __tablename__ = "knowledge_document_issue_types"

    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.document_version_id", ondelete="CASCADE"),
        primary_key=True,
    )
    issue_type: Mapped[CaseIssueType] = mapped_column(
        enum_type(CaseIssueType, "knowledge_case_issue_type"),
        primary_key=True,
    )

    document: Mapped[KnowledgeDocumentRecord] = relationship(back_populates="issue_type_links")


class KnowledgeChunkRecord(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        CheckConstraint("chunk_index >= 0", name="ck_knowledge_chunks_nonnegative_index"),
        UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_knowledge_chunks_document_index",
        ),
    )

    chunk_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    document_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_documents.document_version_id", ondelete="CASCADE"),
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(1000))
    text: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))

    document: Mapped[KnowledgeDocumentRecord] = relationship(back_populates="chunks")
    embeddings: Mapped[list["KnowledgeEmbeddingRecord"]] = relationship(
        back_populates="chunk",
        cascade="all, delete-orphan",
        order_by="KnowledgeEmbeddingRecord.provider_name",
    )


class KnowledgeEmbeddingRecord(Base):
    __tablename__ = "knowledge_embeddings"
    __table_args__ = (CheckConstraint("dimensions > 0", name="ck_knowledge_embeddings_dimensions"),)

    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_chunks.chunk_id", ondelete="CASCADE"), primary_key=True
    )
    provider_name: Mapped[str] = mapped_column(String(500), primary_key=True)
    dimensions: Mapped[int] = mapped_column(Integer)
    vector: Mapped[list[float]] = mapped_column(JSON)
    embedded_at: Mapped[datetime] = mapped_column(UTCDateTime())

    chunk: Mapped[KnowledgeChunkRecord] = relationship(back_populates="embeddings")
