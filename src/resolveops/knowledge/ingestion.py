import hashlib
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from resolveops.database.knowledge_records import (
    KnowledgeChunkRecord,
    KnowledgeDocumentIssueTypeRecord,
    KnowledgeDocumentRecord,
    KnowledgeEmbeddingRecord,
)
from resolveops.knowledge.chunking import chunk_document
from resolveops.knowledge.documents import load_knowledge_document
from resolveops.knowledge.embeddings import EmbeddingProvider
from resolveops.knowledge.models import (
    ChunkEmbedding,
    IngestionReport,
    KnowledgeChunk,
    KnowledgeDocument,
)
from resolveops.security.knowledge import validate_knowledge_security


class KnowledgeVersionConflictError(ValueError):
    pass


class KnowledgeIndexIntegrityError(ValueError):
    pass


def ingest_directory(
    session: Session,
    directory: Path,
    embedding_provider: EmbeddingProvider,
    *,
    ingested_at: datetime,
    max_chunk_characters: int = 1000,
) -> IngestionReport:
    paths = sorted(directory.rglob("*.md"))
    totals = {
        "created_documents": 0,
        "skipped_documents": 0,
        "created_chunks": 0,
        "created_embeddings": 0,
        "skipped_embeddings": 0,
    }
    for path in paths:
        relative_path = path.relative_to(directory).as_posix()
        document = load_knowledge_document(path, source_path=relative_path)
        result = ingest_document(
            session,
            document,
            embedding_provider,
            ingested_at=ingested_at,
            max_chunk_characters=max_chunk_characters,
        )
        for key in totals:
            totals[key] += result[key]
    return IngestionReport(discovered_documents=len(paths), **totals)


def ingest_document(
    session: Session,
    document: KnowledgeDocument,
    embedding_provider: EmbeddingProvider,
    *,
    ingested_at: datetime,
    max_chunk_characters: int = 1000,
) -> dict[str, int]:
    validate_knowledge_security(document)
    chunks = chunk_document(document, max_characters=max_chunk_characters)
    fingerprint = _document_fingerprint(document)
    existing = session.get(KnowledgeDocumentRecord, document.version_id)

    if existing is None:
        session.add(
            KnowledgeDocumentRecord(
                document_version_id=document.version_id,
                document_id=document.document_id,
                title=document.title,
                version=document.version,
                status=document.status,
                source=document.source,
                source_path=document.source_path,
                effective_at=document.effective_at,
                expires_at=document.expires_at,
                fingerprint_sha256=fingerprint,
                ingested_at=ingested_at,
                issue_type_links=[
                    KnowledgeDocumentIssueTypeRecord(
                        document_version_id=document.version_id,
                        issue_type=issue_type,
                    )
                    for issue_type in document.issue_types
                ],
                chunks=[
                    KnowledgeChunkRecord(
                        chunk_id=chunk.chunk_id,
                        document_version_id=chunk.document_version_id,
                        chunk_index=chunk.chunk_index,
                        heading=chunk.heading,
                        text=chunk.text,
                        content_sha256=chunk.content_sha256,
                    )
                    for chunk in chunks
                ],
            )
        )
        session.flush()
        created_documents = 1
        skipped_documents = 0
        created_chunks = len(chunks)
    else:
        if existing.fingerprint_sha256 != fingerprint:
            raise KnowledgeVersionConflictError(
                f"{document.version_id} already exists with different content or metadata"
            )
        _verify_existing_chunks(session, document.version_id, chunks)
        created_documents = 0
        skipped_documents = 1
        created_chunks = 0

    existing_embeddings = list(
        session.scalars(
            select(KnowledgeEmbeddingRecord).where(
                KnowledgeEmbeddingRecord.provider_name == embedding_provider.provider_name,
                KnowledgeEmbeddingRecord.chunk_id.in_([chunk.chunk_id for chunk in chunks]),
            )
        )
    )
    if any(
        embedding.dimensions != embedding_provider.dimensions for embedding in existing_embeddings
    ):
        raise KnowledgeIndexIntegrityError(
            "stored embedding dimensions do not match the provider configuration"
        )
    existing_embedding_ids = {embedding.chunk_id for embedding in existing_embeddings}
    missing_chunks = [chunk for chunk in chunks if chunk.chunk_id not in existing_embedding_ids]
    vectors = embedding_provider.embed_documents([chunk.text for chunk in missing_chunks])
    if len(vectors) != len(missing_chunks):
        raise KnowledgeIndexIntegrityError(
            "embedding provider returned a different number of vectors than chunks"
        )

    for chunk, vector in zip(missing_chunks, vectors, strict=True):
        embedding = ChunkEmbedding(
            chunk_id=chunk.chunk_id,
            provider_name=embedding_provider.provider_name,
            dimensions=embedding_provider.dimensions,
            vector=vector,
            embedded_at=ingested_at,
        )
        session.add(
            KnowledgeEmbeddingRecord(
                chunk_id=embedding.chunk_id,
                provider_name=embedding.provider_name,
                dimensions=embedding.dimensions,
                vector=embedding.vector,
                embedded_at=embedding.embedded_at,
            )
        )
    session.flush()

    return {
        "created_documents": created_documents,
        "skipped_documents": skipped_documents,
        "created_chunks": created_chunks,
        "created_embeddings": len(missing_chunks),
        "skipped_embeddings": len(existing_embedding_ids),
    }


def _verify_existing_chunks(
    session: Session,
    document_version_id: str,
    expected_chunks: list[KnowledgeChunk],
) -> None:
    records = list(
        session.scalars(
            select(KnowledgeChunkRecord)
            .where(KnowledgeChunkRecord.document_version_id == document_version_id)
            .order_by(KnowledgeChunkRecord.chunk_index)
        )
    )
    expected = [
        (chunk.chunk_id, chunk.chunk_index, chunk.content_sha256, chunk.text)
        for chunk in expected_chunks
    ]
    actual = [
        (record.chunk_id, record.chunk_index, record.content_sha256, record.text)
        for record in records
    ]
    if actual != expected:
        raise KnowledgeIndexIntegrityError(
            f"stored chunks for {document_version_id} do not match deterministic chunking"
        )


def _document_fingerprint(document: KnowledgeDocument) -> str:
    payload = document.model_dump(mode="json", exclude={"source_path"})
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
