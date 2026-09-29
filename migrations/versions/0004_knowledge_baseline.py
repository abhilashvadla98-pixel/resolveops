"""Add versioned knowledge documents, chunks, and embeddings.

Revision ID: 0004_knowledge_baseline
Revises: 0003_action_controls
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_knowledge_baseline"
down_revision: str | None = "0003_action_controls"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def text_enum(*values: str, name: str, length: int = 32) -> sa.Enum:
    return sa.Enum(
        *values,
        name=name,
        length=length,
        native_enum=False,
        create_constraint=True,
    )


def upgrade() -> None:
    op.create_table(
        "knowledge_documents",
        sa.Column("document_version_id", sa.String(length=200), primary_key=True),
        sa.Column("document_id", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            text_enum("draft", "active", "superseded", name="knowledge_status"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=1000), nullable=False),
        sa.Column("source_path", sa.String(length=2000), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_knowledge_documents_positive_version"),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > effective_at",
            name="ck_knowledge_documents_effective_order",
        ),
        sa.UniqueConstraint("document_id", "version", name="uq_knowledge_documents_version"),
    )
    op.create_index("ix_knowledge_documents_document_id", "knowledge_documents", ["document_id"])
    op.create_index("ix_knowledge_documents_effective_at", "knowledge_documents", ["effective_at"])

    op.create_table(
        "knowledge_document_issue_types",
        sa.Column(
            "document_version_id",
            sa.String(length=200),
            sa.ForeignKey("knowledge_documents.document_version_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "issue_type",
            text_enum(
                "duplicate_charge",
                "missing_return_refund",
                name="knowledge_case_issue_type",
            ),
            primary_key=True,
        ),
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("chunk_id", sa.String(length=100), primary_key=True),
        sa.Column(
            "document_version_id",
            sa.String(length=200),
            sa.ForeignKey("knowledge_documents.document_version_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(length=1000), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint("chunk_index >= 0", name="ck_knowledge_chunks_nonnegative_index"),
        sa.UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_knowledge_chunks_document_index",
        ),
    )
    op.create_index(
        "ix_knowledge_chunks_document_version_id",
        "knowledge_chunks",
        ["document_version_id"],
    )

    op.create_table(
        "knowledge_embeddings",
        sa.Column(
            "chunk_id",
            sa.String(length=100),
            sa.ForeignKey("knowledge_chunks.chunk_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("provider_name", sa.String(length=500), primary_key=True),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector", sa.JSON(), nullable=False),
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("dimensions > 0", name="ck_knowledge_embeddings_dimensions"),
    )


def downgrade() -> None:
    op.drop_table("knowledge_embeddings")
    op.drop_index("ix_knowledge_chunks_document_version_id", table_name="knowledge_chunks")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_document_issue_types")
    op.drop_index("ix_knowledge_documents_effective_at", table_name="knowledge_documents")
    op.drop_index("ix_knowledge_documents_document_id", table_name="knowledge_documents")
    op.drop_table("knowledge_documents")
