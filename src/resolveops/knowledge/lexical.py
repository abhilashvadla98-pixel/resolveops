import math
from collections import Counter
from dataclasses import dataclass

from resolveops.knowledge.text import tokenize_text


@dataclass(frozen=True)
class LexicalEntry:
    entry_id: str
    text: str


class BM25Index:
    """Small-corpus Okapi BM25 index with deterministic ranking."""

    def __init__(
        self,
        entries: list[LexicalEntry],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        if k1 <= 0:
            raise ValueError("BM25 k1 must be positive")
        if not 0 <= b <= 1:
            raise ValueError("BM25 b must be between 0 and 1")
        if len({entry.entry_id for entry in entries}) != len(entries):
            raise ValueError("BM25 entry IDs must be unique")
        self.entries = entries
        self.k1 = k1
        self.b = b
        self.term_frequencies = [Counter(tokenize_text(entry.text)) for entry in entries]
        self.document_lengths = [sum(frequencies.values()) for frequencies in self.term_frequencies]
        self.average_document_length = (
            sum(self.document_lengths) / len(self.document_lengths) if entries else 0.0
        )
        self.document_frequencies = Counter(
            term for frequencies in self.term_frequencies for term in frequencies
        )

    def search(self, query: str, *, top_k: int) -> list[tuple[str, float]]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        query_frequencies = Counter(tokenize_text(query))
        if not query_frequencies or not self.entries:
            return []

        scored: list[tuple[str, float]] = []
        document_count = len(self.entries)
        for entry, frequencies, document_length in zip(
            self.entries,
            self.term_frequencies,
            self.document_lengths,
            strict=True,
        ):
            score = 0.0
            for term, query_frequency in query_frequencies.items():
                term_frequency = frequencies.get(term, 0)
                if term_frequency == 0:
                    continue
                document_frequency = self.document_frequencies[term]
                inverse_document_frequency = math.log(
                    1.0 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                length_ratio = (
                    document_length / self.average_document_length
                    if self.average_document_length
                    else 0.0
                )
                denominator = term_frequency + self.k1 * (1.0 - self.b + self.b * length_ratio)
                score += (
                    query_frequency
                    * inverse_document_frequency
                    * term_frequency
                    * (self.k1 + 1.0)
                    / denominator
                )
            if score > 0:
                scored.append((entry.entry_id, score))

        scored.sort(key=lambda item: (-item[1], item[0]))
        return scored[:top_k]
