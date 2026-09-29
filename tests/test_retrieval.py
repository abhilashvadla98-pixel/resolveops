import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from resolveops.database.base import Base
from resolveops.knowledge.embeddings import FeatureHashEmbeddingProvider
from resolveops.knowledge.evaluation import evaluate_retriever, load_evaluation_cases
from resolveops.knowledge.ingestion import ingest_directory
from resolveops.knowledge.lexical import BM25Index, LexicalEntry
from resolveops.knowledge.models import (
    RetrievalEvaluationCase,
    RetrievalMethod,
    RetrievalResult,
)
from resolveops.knowledge.retrieval import (
    HybridPolicyRetriever,
    LexicalPolicyRetriever,
    PolicyRetriever,
)
from resolveops.models.case import CaseIssueType

POLICY_DIRECTORY = Path("domain_packs/customer_operations/policies")
EVALUATION_DATASET = Path("evals/retrieval/customer_operations.jsonl")
NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


def sqlite_engine() -> Engine:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection: object, connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


def test_bm25_prioritizes_specific_matching_terms() -> None:
    index = BM25Index(
        [
            LexicalEntry("duplicate", "two captured payment identifiers same amount currency"),
            LexicalEntry("return", "warehouse received returned item original price"),
            LexicalEntry("communication", "verified customer email notification"),
        ]
    )

    results = index.search("captured payment amount currency", top_k=2)

    assert results[0][0] == "duplicate"
    assert results[0][1] > results[1][1] if len(results) > 1 else True


def test_lexical_and_hybrid_retrieval_include_ranking_evidence() -> None:
    engine = sqlite_engine()
    provider = FeatureHashEmbeddingProvider(dimensions=384)
    with Session(engine) as session:
        ingest_directory(session, POLICY_DIRECTORY, provider, ingested_at=NOW)
        session.commit()

        lexical = LexicalPolicyRetriever(session).search(
            "returned quantity original unit price",
            as_of=NOW,
            issue_type=CaseIssueType.MISSING_RETURN_REFUND,
            top_k=3,
        )
        hybrid = HybridPolicyRetriever(session, provider).search(
            "two captured payments same amount currency",
            as_of=NOW,
            issue_type=CaseIssueType.DUPLICATE_CHARGE,
            top_k=3,
        )

        assert lexical[0].document_id == "POLICY-RETURN-REFUND"
        assert lexical[0].method == RetrievalMethod.LEXICAL
        assert lexical[0].lexical_rank == 1
        assert lexical[0].lexical_score is not None
        assert hybrid[0].document_id == "POLICY-DUPLICATE-CHARGE"
        assert hybrid[0].method == RetrievalMethod.HYBRID
        assert hybrid[0].vector_rank is not None
        assert hybrid[0].lexical_rank is not None
        assert hybrid[0].vector_score is not None
        assert hybrid[0].lexical_score is not None
    engine.dispose()


def test_hybrid_retrieval_falls_back_to_bm25_without_matching_embeddings() -> None:
    engine = sqlite_engine()
    indexed_provider = FeatureHashEmbeddingProvider(dimensions=128)
    unavailable_provider = FeatureHashEmbeddingProvider(dimensions=256)
    with Session(engine) as session:
        ingest_directory(session, POLICY_DIRECTORY, indexed_provider, ingested_at=NOW)
        session.commit()

        results = HybridPolicyRetriever(session, unavailable_provider).search(
            "verified customer email recipient",
            as_of=NOW,
            top_k=1,
        )

        assert results[0].document_id == "POLICY-CUSTOMER-COMMUNICATION"
        assert results[0].vector_rank is None
        assert results[0].lexical_rank == 1
    engine.dispose()


def test_evaluation_dataset_is_valid_and_covers_all_policies() -> None:
    cases = load_evaluation_cases(EVALUATION_DATASET)
    dataset_hash = hashlib.sha256(EVALUATION_DATASET.read_bytes()).hexdigest()
    evaluation_readme = Path("evals/retrieval/README.md").read_text(encoding="utf-8")

    assert len(cases) == 50
    assert dataset_hash in evaluation_readme
    assert {case.category.value for case in cases} == {
        "direct_lookup",
        "hard_negative",
        "similar_policy",
        "wrong_issue_type",
        "multi_section",
        "confusing_terminology",
    }
    assert {document_id for case in cases for document_id in case.relevant_document_ids} == {
        "POLICY-CASE-ESCALATION",
        "POLICY-CUSTOMER-COMMUNICATION",
        "POLICY-DUPLICATE-CHARGE",
        "POLICY-PAYMENT-STATUS",
        "POLICY-RETURN-ELIGIBILITY",
        "POLICY-RETURN-REFUND",
    }


def test_metrics_use_unique_document_ranks() -> None:
    class FixedRetriever:
        def search(
            self,
            query: str,
            *,
            as_of: datetime,
            issue_type: CaseIssueType | None = None,
            top_k: int = 5,
        ) -> list[RetrievalResult]:
            documents = ["A", "A", "C", "B"] if query == "first" else ["C", "D"]
            return [result(document_id, rank) for rank, document_id in enumerate(documents, 1)]

    cases = [
        RetrievalEvaluationCase(
            case_id="CASE-A",
            query="first",
            relevant_document_ids=["A", "B"],
        ),
        RetrievalEvaluationCase(
            case_id="CASE-B",
            query="second",
            relevant_document_ids=["D"],
        ),
    ]

    metrics = evaluate_retriever(FixedRetriever(), RetrievalMethod.HYBRID, cases, as_of=NOW, k=2)

    assert metrics.recall_at_k == pytest.approx(0.75)
    assert metrics.mrr == pytest.approx(0.75)
    assert metrics.ndcg_at_k == pytest.approx(0.622038473168458)
    assert metrics.cases[0].retrieved_document_ids == ["A", "C"]


def test_hybrid_evaluation_runs_reproducibly() -> None:
    engine = sqlite_engine()
    provider = FeatureHashEmbeddingProvider(dimensions=384)
    cases = load_evaluation_cases(EVALUATION_DATASET)
    with Session(engine) as session:
        ingest_directory(session, POLICY_DIRECTORY, provider, ingested_at=NOW)
        session.commit()
        first = evaluate_retriever(
            HybridPolicyRetriever(session, provider),
            RetrievalMethod.HYBRID,
            cases,
            as_of=NOW,
            k=3,
        )
        second = evaluate_retriever(
            HybridPolicyRetriever(session, provider),
            RetrievalMethod.HYBRID,
            cases,
            as_of=NOW,
            k=3,
        )

        assert first == second
        assert first.query_count == 50
        assert {item.category.value for item in first.category_metrics} == {
            "direct_lookup",
            "hard_negative",
            "similar_policy",
            "wrong_issue_type",
            "multi_section",
            "confusing_terminology",
        }
        assert first.recall_at_k >= 0.9
        assert first.mrr >= 0.85
        assert first.ndcg_at_k >= 0.85

        vector = evaluate_retriever(
            PolicyRetriever(session, provider),
            RetrievalMethod.VECTOR,
            cases,
            as_of=NOW,
            k=3,
        )
        assert first.recall_at_k >= vector.recall_at_k
        assert first.mrr >= vector.mrr
        assert first.ndcg_at_k >= vector.ndcg_at_k
    engine.dispose()


def result(document_id: str, rank: int) -> RetrievalResult:
    return RetrievalResult(
        rank=rank,
        score=1.0 / rank,
        method=RetrievalMethod.HYBRID,
        chunk_id=f"CHUNK-{document_id}-{rank}",
        document_id=document_id,
        document_version=1,
        title=f"Policy {document_id}",
        heading="Section",
        text="Policy evidence",
        source="test",
        effective_at=NOW,
    )
