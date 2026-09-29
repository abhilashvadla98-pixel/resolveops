import json
import math
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from resolveops.knowledge.models import (
    RetrievalCaseResult,
    RetrievalCategoryMetrics,
    RetrievalEvaluationCase,
    RetrievalMethod,
    RetrievalMetrics,
    RetrievalResult,
)
from resolveops.models.case import CaseIssueType


class SearchableRetriever(Protocol):
    def search(
        self,
        query: str,
        *,
        as_of: datetime,
        issue_type: CaseIssueType | None = None,
        top_k: int = 5,
    ) -> list[RetrievalResult]: ...


class RetrievalDatasetError(ValueError):
    pass


def load_evaluation_cases(path: Path) -> list[RetrievalEvaluationCase]:
    cases: list[RetrievalEvaluationCase] = []
    seen_ids: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RetrievalDatasetError(f"cannot read retrieval dataset {path}") from exc

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            evaluation_case = RetrievalEvaluationCase.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise RetrievalDatasetError(f"invalid retrieval case at {path}:{line_number}") from exc
        if evaluation_case.case_id in seen_ids:
            raise RetrievalDatasetError(f"duplicate retrieval case ID {evaluation_case.case_id}")
        seen_ids.add(evaluation_case.case_id)
        cases.append(evaluation_case)
    if not cases:
        raise RetrievalDatasetError("retrieval dataset cannot be empty")
    return cases


def evaluate_retriever(
    retriever: SearchableRetriever,
    method: RetrievalMethod,
    cases: Sequence[RetrievalEvaluationCase],
    *,
    as_of: datetime,
    k: int,
) -> RetrievalMetrics:
    if not cases:
        raise ValueError("retrieval evaluation requires at least one case")
    if not 1 <= k <= 20:
        raise ValueError("evaluation k must be between 1 and 20")

    case_results: list[RetrievalCaseResult] = []
    candidate_depth = 100
    for evaluation_case in cases:
        results = retriever.search(
            evaluation_case.query,
            as_of=as_of,
            issue_type=evaluation_case.issue_type,
            top_k=candidate_depth,
        )
        document_ids = _unique_document_ids(results)[:k]
        relevant = set(evaluation_case.relevant_document_ids)
        recall = len(relevant.intersection(document_ids)) / len(relevant)
        reciprocal_rank = _reciprocal_rank(document_ids, relevant)
        ndcg = _ndcg_at_k(document_ids, relevant, k)
        case_results.append(
            RetrievalCaseResult(
                case_id=evaluation_case.case_id,
                category=evaluation_case.category,
                retrieved_document_ids=document_ids,
                recall_at_k=recall,
                reciprocal_rank=reciprocal_rank,
                ndcg_at_k=ndcg,
            )
        )

    count = len(case_results)
    category_metrics = []
    for category in sorted({item.category for item in case_results}, key=lambda item: item.value):
        matching = [item for item in case_results if item.category == category]
        category_metrics.append(
            RetrievalCategoryMetrics(
                category=category,
                query_count=len(matching),
                recall_at_k=sum(item.recall_at_k for item in matching) / len(matching),
                mrr=sum(item.reciprocal_rank for item in matching) / len(matching),
                ndcg_at_k=sum(item.ndcg_at_k for item in matching) / len(matching),
            )
        )
    return RetrievalMetrics(
        method=method,
        query_count=count,
        k=k,
        recall_at_k=sum(item.recall_at_k for item in case_results) / count,
        mrr=sum(item.reciprocal_rank for item in case_results) / count,
        ndcg_at_k=sum(item.ndcg_at_k for item in case_results) / count,
        category_metrics=category_metrics,
        cases=case_results,
    )


def _unique_document_ids(results: Sequence[RetrievalResult]) -> list[str]:
    seen: set[str] = set()
    document_ids: list[str] = []
    for result in results:
        if result.document_id not in seen:
            seen.add(result.document_id)
            document_ids.append(result.document_id)
    return document_ids


def _reciprocal_rank(document_ids: Sequence[str], relevant: set[str]) -> float:
    for rank, document_id in enumerate(document_ids, start=1):
        if document_id in relevant:
            return 1.0 / rank
    return 0.0


def _ndcg_at_k(document_ids: Sequence[str], relevant: set[str], k: int) -> float:
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, document_id in enumerate(document_ids[:k], start=1)
        if document_id in relevant
    )
    ideal_hits = min(k, len(relevant))
    ideal_dcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / ideal_dcg if ideal_dcg else 0.0
