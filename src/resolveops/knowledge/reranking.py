from __future__ import annotations

import importlib
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol

from resolveops.knowledge.evaluation import SearchableRetriever
from resolveops.knowledge.models import RetrievalMethod, RetrievalResult
from resolveops.models.case import CaseIssueType


class CrossEncoderReranker(Protocol):
    @property
    def model_name(self) -> str: ...

    def score(self, query: str, documents: Sequence[str]) -> list[float]: ...


class FastEmbedCrossEncoderReranker:
    def __init__(self, model_name: str = "Xenova/ms-marco-MiniLM-L-6-v2") -> None:
        module = importlib.import_module("fastembed.rerank.cross_encoder")
        model_class: Any = module.TextCrossEncoder
        self._model: Any = model_class(model_name=model_name)
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        scores = [float(value) for value in self._model.rerank(query, documents)]
        if len(scores) != len(documents):
            raise RuntimeError("cross-encoder returned an unexpected score count")
        return scores


class RerankedPolicyRetriever:
    """Experimental reranker wrapper; not used by the production retrieval path."""

    def __init__(
        self,
        base: SearchableRetriever,
        reranker: CrossEncoderReranker,
        *,
        candidate_pool: int = 20,
    ) -> None:
        if not 1 <= candidate_pool <= 100:
            raise ValueError("reranker candidate pool must be between 1 and 100")
        self.base = base
        self.reranker = reranker
        self.candidate_pool = candidate_pool

    def search(
        self,
        query: str,
        *,
        as_of: datetime,
        issue_type: CaseIssueType | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        candidates = self.base.search(
            query,
            as_of=as_of,
            issue_type=issue_type,
            top_k=max(top_k, self.candidate_pool),
        )
        if not candidates:
            return []
        scores = self.reranker.score(query, [candidate.text for candidate in candidates])
        ranked = sorted(
            zip(candidates, scores, strict=True),
            key=lambda item: (-item[1], item[0].chunk_id),
        )
        results: list[RetrievalResult] = []
        for rank, (candidate, _) in enumerate(ranked[:top_k], start=1):
            payload = candidate.model_dump()
            payload.update(
                {
                    "rank": rank,
                    "score": 1.0 / (60 + rank),
                    "method": RetrievalMethod.HYBRID,
                }
            )
            results.append(RetrievalResult.model_validate(payload))
        return results
