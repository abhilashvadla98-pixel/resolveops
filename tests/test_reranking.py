from datetime import UTC, datetime

from resolveops.knowledge.models import RetrievalMethod, RetrievalResult
from resolveops.knowledge.reranking import RerankedPolicyRetriever

NOW = datetime(2026, 9, 29, tzinfo=UTC)


def _result(chunk_id: str, text: str, rank: int) -> RetrievalResult:
    return RetrievalResult(
        rank=rank,
        score=1 / (60 + rank),
        method=RetrievalMethod.HYBRID,
        chunk_id=chunk_id,
        document_id=f"DOC-{chunk_id}",
        document_version=1,
        title=f"Policy {chunk_id}",
        heading="Policy",
        text=text,
        source=f"test://{chunk_id}",
        effective_at=NOW,
    )


class BaseRetriever:
    def search(self, query, *, as_of, issue_type=None, top_k=5):  # type: ignore[no-untyped-def]
        return [_result("A", "weak match", 1), _result("B", "strong match", 2)][:top_k]


class FakeReranker:
    model_name = "fake-cross-encoder"

    def score(self, query: str, documents: list[str]) -> list[float]:
        return [0.1, 0.9]


def test_experimental_reranker_reorders_candidates_without_changing_contract() -> None:
    retriever = RerankedPolicyRetriever(BaseRetriever(), FakeReranker(), candidate_pool=2)

    results = retriever.search("strong", as_of=NOW, top_k=2)

    assert [item.chunk_id for item in results] == ["B", "A"]
    assert [item.rank for item in results] == [1, 2]
    assert all(item.method == RetrievalMethod.HYBRID for item in results)
