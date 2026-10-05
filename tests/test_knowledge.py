from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, event, func, select
from sqlalchemy.orm import Session

from resolveops.database.base import Base
from resolveops.database.knowledge_records import (
    KnowledgeChunkRecord,
    KnowledgeDocumentRecord,
    KnowledgeEmbeddingRecord,
)
from resolveops.knowledge.chunking import chunk_document
from resolveops.knowledge.documents import (
    KnowledgeDocumentError,
    load_knowledge_document,
    parse_knowledge_document,
)
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.knowledge.ingestion import (
    KnowledgeVersionConflictError,
    ingest_directory,
    ingest_document,
)
from resolveops.knowledge.models import KnowledgeDocument
from resolveops.knowledge.retrieval import PolicyRetriever
from resolveops.knowledge.vector_index import ExactVectorIndex, VectorEntry
from resolveops.models.case import CaseIssueType

POLICY_DIRECTORY = Path("domain_packs/customer_operations/policies")
INGESTED_AT = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def sqlite_engine() -> Engine:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


def test_policy_documents_have_valid_versioned_metadata() -> None:
    documents = [
        load_knowledge_document(path, source_path=path.name)
        for path in sorted(POLICY_DIRECTORY.glob("*.md"))
    ]

    assert len(documents) == 8
    assert len({document.version_id for document in documents}) == 8
    assert all(document.status.value == "active" for document in documents)
    assert all(document.effective_at.tzinfo is not None for document in documents)


def test_parser_rejects_missing_or_invalid_front_matter() -> None:
    with pytest.raises(KnowledgeDocumentError, match="must start"):
        parse_knowledge_document("# No metadata", source_path="bad.md")

    with pytest.raises(KnowledgeDocumentError, match="invalid knowledge document metadata"):
        parse_knowledge_document(
            """+++
document_id = "POLICY-BAD"
title = "Bad policy"
version = 0
status = "active"
issue_types = ["duplicate_charge"]
source = "test"
effective_at = 2026-01-01T00:00:00Z
+++
# Bad policy
Invalid metadata should not ingest.
""",
            source_path="bad.md",
        )


def test_chunking_is_heading_aware_bounded_and_deterministic() -> None:
    document = load_knowledge_document(
        POLICY_DIRECTORY / "duplicate_charge_v1.md",
        source_path="duplicate_charge_v1.md",
    )
    first = chunk_document(document, max_characters=500)
    second = chunk_document(document, max_characters=500)

    assert first == second
    assert len(first) >= 4
    assert [chunk.chunk_index for chunk in first] == list(range(len(first)))
    assert all(len(chunk.text) <= 500 for chunk in first)
    assert any(chunk.heading == "Required evidence" for chunk in first)


def test_ingestion_is_repeatable_and_preserves_separate_embeddings() -> None:
    engine = sqlite_engine()
    provider = FeatureHashEmbeddingProvider(dimensions=128)
    with Session(engine) as session:
        first = ingest_directory(session, POLICY_DIRECTORY, provider, ingested_at=INGESTED_AT)
        session.commit()
        second = ingest_directory(session, POLICY_DIRECTORY, provider, ingested_at=INGESTED_AT)
        session.commit()

        chunk_count = session.scalar(select(func.count()).select_from(KnowledgeChunkRecord))
        embedding_count = session.scalar(select(func.count()).select_from(KnowledgeEmbeddingRecord))
        assert first.created_documents == 8
        assert first.created_chunks == chunk_count
        assert first.created_embeddings == embedding_count
        assert second.created_documents == 0
        assert second.skipped_documents == 8
        assert second.created_embeddings == 0
        assert second.skipped_embeddings == embedding_count
    engine.dispose()


def test_same_document_version_cannot_silently_change() -> None:
    engine = sqlite_engine()
    provider = FeatureHashEmbeddingProvider(dimensions=128)
    original = load_knowledge_document(
        POLICY_DIRECTORY / "return_refund_v1.md",
        source_path="return_refund_v1.md",
    )
    changed = original.model_copy(
        update={"content": f"{original.content}\n\nUndeclared same-version change."}
    )
    assert isinstance(changed, KnowledgeDocument)

    with Session(engine) as session:
        ingest_document(session, original, provider, ingested_at=INGESTED_AT)
        session.commit()
        with pytest.raises(KnowledgeVersionConflictError, match="different content"):
            ingest_document(session, changed, provider, ingested_at=INGESTED_AT)
    engine.dispose()


@pytest.mark.parametrize(
    ("query", "issue_type", "expected_document"),
    [
        (
            "two distinct captured payments same order amount currency full refund",
            CaseIssueType.DUPLICATE_CHARGE,
            "POLICY-DUPLICATE-CHARGE",
        ),
        (
            "received return item quantity original unit price active refunds",
            CaseIssueType.MISSING_RETURN_REFUND,
            "POLICY-RETURN-REFUND",
        ),
        (
            "completed partial refund expected returned item value remaining balance",
            CaseIssueType.INCORRECT_REFUND_AMOUNT,
            "POLICY-REFUND-AMOUNT",
        ),
        (
            "cancelled order full captured payment remaining refundable amount",
            CaseIssueType.CANCELLED_ORDER_CHARGE,
            "POLICY-CANCELLED-ORDER-CHARGE",
        ),
        (
            "verified customer email recipient notification delivery",
            None,
            "POLICY-CUSTOMER-COMMUNICATION",
        ),
    ],
)
def test_vector_retrieval_returns_relevant_cited_policy(
    query: str,
    issue_type: CaseIssueType | None,
    expected_document: str,
) -> None:
    engine = sqlite_engine()
    provider = FeatureHashEmbeddingProvider(dimensions=384)
    with Session(engine) as session:
        ingest_directory(session, POLICY_DIRECTORY, provider, ingested_at=INGESTED_AT)
        session.commit()
        results = PolicyRetriever(session, provider).search(
            query,
            as_of=datetime(2026, 9, 24, tzinfo=UTC),
            issue_type=issue_type,
            top_k=3,
        )

        assert results
        assert results[0].document_id == expected_document
        assert results[0].rank == 1
        assert results[0].source == "ResolveOps Customer Operations policy library"
        assert results[0].text
        assert results[0].chunk_id.startswith("KCH-")
    engine.dispose()


def test_retrieval_enforces_effective_date_and_timezone() -> None:
    engine = sqlite_engine()
    provider = FeatureHashEmbeddingProvider(dimensions=128)
    with Session(engine) as session:
        ingest_directory(session, POLICY_DIRECTORY, provider, ingested_at=INGESTED_AT)
        session.commit()
        retriever = PolicyRetriever(session, provider)

        assert (
            retriever.search(
                "duplicate captured payment",
                as_of=datetime(2025, 12, 31, tzinfo=UTC),
            )
            == []
        )
        with pytest.raises(ValueError, match="timezone"):
            naive_time = datetime(2026, 9, 24, tzinfo=UTC).replace(tzinfo=None)
            retriever.search("duplicate payment", as_of=naive_time)
    engine.dispose()


def test_ingested_documents_are_queryable_by_version() -> None:
    engine = sqlite_engine()
    provider = FeatureHashEmbeddingProvider(dimensions=128)
    with Session(engine) as session:
        ingest_directory(session, POLICY_DIRECTORY, provider, ingested_at=INGESTED_AT)
        session.commit()
        records = list(
            session.scalars(
                select(KnowledgeDocumentRecord).order_by(KnowledgeDocumentRecord.document_id)
            )
        )
        assert [(record.document_id, record.version) for record in records] == [
            ("POLICY-CANCELLED-ORDER-CHARGE", 1),
            ("POLICY-CASE-ESCALATION", 1),
            ("POLICY-CUSTOMER-COMMUNICATION", 1),
            ("POLICY-DUPLICATE-CHARGE", 1),
            ("POLICY-PAYMENT-STATUS", 1),
            ("POLICY-REFUND-AMOUNT", 1),
            ("POLICY-RETURN-ELIGIBILITY", 1),
            ("POLICY-RETURN-REFUND", 1),
        ]
    engine.dispose()


def test_vector_index_rejects_invalid_dimensions_and_zero_queries() -> None:
    index = ExactVectorIndex([VectorEntry(entry_id="one", vector=[1.0, 0.0])], dimensions=2)
    with pytest.raises(ValueError, match="query vector dimensions"):
        index.search([1.0], top_k=1)
    with pytest.raises(ValueError, match="finite, non-zero"):
        index.search([0.0, 0.0], top_k=1)
