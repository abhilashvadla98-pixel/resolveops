import math
from dataclasses import dataclass


@dataclass(frozen=True)
class VectorEntry:
    entry_id: str
    vector: list[float]


class ExactVectorIndex:
    """Deterministic exact cosine index used by the retrieval baseline."""

    def __init__(self, entries: list[VectorEntry], *, dimensions: int) -> None:
        if dimensions <= 0:
            raise ValueError("vector index dimensions must be positive")
        if any(len(entry.vector) != dimensions for entry in entries):
            raise ValueError("every indexed vector must match index dimensions")
        if any(not _valid_vector(entry.vector) for entry in entries):
            raise ValueError("indexed vectors must contain finite, non-zero values")
        self.entries = entries
        self.dimensions = dimensions

    def search(self, query_vector: list[float], *, top_k: int) -> list[tuple[str, float]]:
        if len(query_vector) != self.dimensions:
            raise ValueError("query vector dimensions do not match the index")
        if not _valid_vector(query_vector):
            raise ValueError("query vector must contain finite, non-zero values")
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        scored = [
            (entry.entry_id, _cosine_similarity(query_vector, entry.vector))
            for entry in self.entries
        ]
        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored[:top_k]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("cosine similarity requires non-zero vectors")
    score = sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
    return max(-1.0, min(1.0, score))


def _valid_vector(vector: list[float]) -> bool:
    return all(math.isfinite(value) for value in vector) and any(value != 0 for value in vector)
