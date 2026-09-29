from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from resolveops.database.knowledge_records import (
    KnowledgeChunkRecord,
    KnowledgeDocumentIssueTypeRecord,
    KnowledgeDocumentRecord,
    KnowledgeEmbeddingRecord,
)
from resolveops.knowledge.embeddings import EmbeddingProvider
from resolveops.knowledge.lexical import BM25Index, LexicalEntry
from resolveops.knowledge.models import (
    KnowledgeStatus,
    RetrievalMethod,
    RetrievalResult,
)
from resolveops.knowledge.vector_index import ExactVectorIndex, VectorEntry
from resolveops.models.case import CaseIssueType
from resolveops.observability.models import TraceComponent
from resolveops.observability.sinks import DEFAULT_TRACE_SINK, TraceSink
from resolveops.observability.tracing import observed_span


class PolicyRetriever:
    def __init__(self, session: Session, embedding_provider: EmbeddingProvider) -> None:
        self.session = session
        self.embedding_provider = embedding_provider

    def search(
        self,
        query: str,
        *,
        as_of: datetime,
        issue_type: CaseIssueType | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        _validate_search(query, as_of, top_k)

        statement = (
            select(
                KnowledgeChunkRecord,
                KnowledgeDocumentRecord,
                KnowledgeEmbeddingRecord,
            )
            .join(
                KnowledgeDocumentRecord,
                KnowledgeChunkRecord.document_version_id
                == KnowledgeDocumentRecord.document_version_id,
            )
            .join(
                KnowledgeEmbeddingRecord,
                KnowledgeEmbeddingRecord.chunk_id == KnowledgeChunkRecord.chunk_id,
            )
            .where(
                KnowledgeEmbeddingRecord.provider_name == self.embedding_provider.provider_name,
                KnowledgeEmbeddingRecord.dimensions == self.embedding_provider.dimensions,
                KnowledgeDocumentRecord.status == KnowledgeStatus.ACTIVE,
                KnowledgeDocumentRecord.effective_at <= as_of,
                or_(
                    KnowledgeDocumentRecord.expires_at.is_(None),
                    KnowledgeDocumentRecord.expires_at > as_of,
                ),
            )
        )
        if issue_type is not None:
            statement = statement.where(
                KnowledgeDocumentRecord.issue_type_links.any(
                    KnowledgeDocumentIssueTypeRecord.issue_type == issue_type
                )
            )

        rows = list(self.session.execute(statement))
        entries = [
            VectorEntry(
                entry_id=chunk.chunk_id,
                vector=[float(value) for value in embedding.vector],
            )
            for chunk, _, embedding in rows
        ]
        if not entries:
            return []

        index = ExactVectorIndex(entries, dimensions=self.embedding_provider.dimensions)
        ranked = index.search(self.embedding_provider.embed_query(query), top_k=top_k)
        row_by_chunk = {chunk.chunk_id: (chunk, document) for chunk, document, _ in rows}
        return [
            RetrievalResult(
                rank=rank,
                score=score,
                method=RetrievalMethod.VECTOR,
                chunk_id=chunk_id,
                document_id=row_by_chunk[chunk_id][1].document_id,
                document_version=row_by_chunk[chunk_id][1].version,
                title=row_by_chunk[chunk_id][1].title,
                heading=row_by_chunk[chunk_id][0].heading,
                text=row_by_chunk[chunk_id][0].text,
                source=row_by_chunk[chunk_id][1].source,
                effective_at=row_by_chunk[chunk_id][1].effective_at,
                expires_at=row_by_chunk[chunk_id][1].expires_at,
                vector_rank=rank,
                vector_score=score,
            )
            for rank, (chunk_id, score) in enumerate(ranked, start=1)
        ]


class LexicalPolicyRetriever:
    def __init__(self, session: Session) -> None:
        self.session = session

    def search(
        self,
        query: str,
        *,
        as_of: datetime,
        issue_type: CaseIssueType | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        _validate_search(query, as_of, top_k)
        statement = (
            select(KnowledgeChunkRecord, KnowledgeDocumentRecord)
            .join(
                KnowledgeDocumentRecord,
                KnowledgeChunkRecord.document_version_id
                == KnowledgeDocumentRecord.document_version_id,
            )
            .where(
                KnowledgeDocumentRecord.status == KnowledgeStatus.ACTIVE,
                KnowledgeDocumentRecord.effective_at <= as_of,
                or_(
                    KnowledgeDocumentRecord.expires_at.is_(None),
                    KnowledgeDocumentRecord.expires_at > as_of,
                ),
            )
        )
        if issue_type is not None:
            statement = statement.where(
                KnowledgeDocumentRecord.issue_type_links.any(
                    KnowledgeDocumentIssueTypeRecord.issue_type == issue_type
                )
            )

        rows = list(self.session.execute(statement))
        index = BM25Index(
            [LexicalEntry(entry_id=chunk.chunk_id, text=chunk.text) for chunk, _ in rows]
        )
        ranked = index.search(query, top_k=top_k)
        row_by_chunk = {chunk.chunk_id: (chunk, document) for chunk, document in rows}
        return [
            RetrievalResult(
                rank=rank,
                score=score,
                method=RetrievalMethod.LEXICAL,
                chunk_id=chunk_id,
                document_id=row_by_chunk[chunk_id][1].document_id,
                document_version=row_by_chunk[chunk_id][1].version,
                title=row_by_chunk[chunk_id][1].title,
                heading=row_by_chunk[chunk_id][0].heading,
                text=row_by_chunk[chunk_id][0].text,
                source=row_by_chunk[chunk_id][1].source,
                effective_at=row_by_chunk[chunk_id][1].effective_at,
                expires_at=row_by_chunk[chunk_id][1].expires_at,
                lexical_rank=rank,
                lexical_score=score,
            )
            for rank, (chunk_id, score) in enumerate(ranked, start=1)
        ]


class HybridPolicyRetriever:
    def __init__(
        self,
        session: Session,
        embedding_provider: EmbeddingProvider,
        *,
        vector_weight: float = 1.0,
        lexical_weight: float = 1.0,
        rrf_k: int = 60,
        candidate_pool: int = 50,
        observability_sink: TraceSink | None = None,
    ) -> None:
        if vector_weight < 0 or lexical_weight < 0:
            raise ValueError("retrieval weights cannot be negative")
        if vector_weight + lexical_weight == 0:
            raise ValueError("at least one retrieval weight must be positive")
        if rrf_k <= 0:
            raise ValueError("RRF k must be positive")
        if not 1 <= candidate_pool <= 100:
            raise ValueError("candidate_pool must be between 1 and 100")
        total_weight = vector_weight + lexical_weight
        self.vector_weight = vector_weight / total_weight
        self.lexical_weight = lexical_weight / total_weight
        self.rrf_k = rrf_k
        self.candidate_pool = candidate_pool
        self.observability_sink = observability_sink or DEFAULT_TRACE_SINK
        self.vector = PolicyRetriever(session, embedding_provider)
        self.lexical = LexicalPolicyRetriever(session)

    def search(
        self,
        query: str,
        *,
        as_of: datetime,
        issue_type: CaseIssueType | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        with observed_span(
            TraceComponent.RETRIEVAL,
            "hybrid_policy_search",
            sink=self.observability_sink,
            attributes={
                "embedding_provider": self.vector.embedding_provider.provider_name,
                "top_k": top_k,
                "issue_type": issue_type.value if issue_type else None,
            },
        ) as span:
            results = self._search(
                query,
                as_of=as_of,
                issue_type=issue_type,
                top_k=top_k,
            )
            span.set_attribute("result_count", len(results))
            return results

    def _search(
        self,
        query: str,
        *,
        as_of: datetime,
        issue_type: CaseIssueType | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        _validate_search(query, as_of, top_k)
        candidate_limit = max(top_k, self.candidate_pool)
        vector_results = self.vector.search(
            query,
            as_of=as_of,
            issue_type=issue_type,
            top_k=candidate_limit,
        )
        lexical_results = self.lexical.search(
            query,
            as_of=as_of,
            issue_type=issue_type,
            top_k=candidate_limit,
        )
        by_chunk = {result.chunk_id: result for result in vector_results}
        by_chunk.update({result.chunk_id: result for result in lexical_results})
        vector_by_chunk = {result.chunk_id: result for result in vector_results}
        lexical_by_chunk = {result.chunk_id: result for result in lexical_results}

        fused: list[tuple[str, float]] = []
        for chunk_id in by_chunk:
            vector_result = vector_by_chunk.get(chunk_id)
            lexical_result = lexical_by_chunk.get(chunk_id)
            score = 0.0
            if vector_result is not None:
                score += self.vector_weight / (self.rrf_k + vector_result.rank)
            if lexical_result is not None:
                score += self.lexical_weight / (self.rrf_k + lexical_result.rank)
            fused.append((chunk_id, score))
        fused.sort(key=lambda item: (-item[1], item[0]))

        results: list[RetrievalResult] = []
        for rank, (chunk_id, fused_score) in enumerate(fused[:top_k], start=1):
            source = by_chunk[chunk_id]
            vector_result = vector_by_chunk.get(chunk_id)
            lexical_result = lexical_by_chunk.get(chunk_id)
            payload = source.model_dump()
            payload.update(
                {
                    "rank": rank,
                    "score": fused_score,
                    "method": RetrievalMethod.HYBRID,
                    "vector_rank": vector_result.rank if vector_result else None,
                    "lexical_rank": lexical_result.rank if lexical_result else None,
                    "vector_score": vector_result.score if vector_result else None,
                    "lexical_score": lexical_result.score if lexical_result else None,
                }
            )
            results.append(RetrievalResult.model_validate(payload))
        return results


def _validate_search(query: str, as_of: datetime, top_k: int) -> None:
    if not query.strip():
        raise ValueError("retrieval query cannot be empty")
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must include a timezone")
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")
