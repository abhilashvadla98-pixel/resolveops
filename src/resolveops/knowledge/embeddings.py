import hashlib
import importlib
import math
from collections import Counter
from collections.abc import Sequence
from itertools import pairwise
from typing import Any, Protocol

from resolveops.knowledge.text import tokenize_text


class EmbeddingProvider(Protocol):
    @property
    def provider_name(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FeatureHashEmbeddingProvider:
    """Small deterministic baseline for offline development and tests."""

    def __init__(self, *, dimensions: int = 384) -> None:
        if dimensions < 64:
            raise ValueError("feature-hash embeddings require at least 64 dimensions")
        self._dimensions = dimensions

    @property
    def provider_name(self) -> str:
        return f"feature-hash-v1:{self.dimensions}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        tokens = tokenize_text(text)
        features = [*tokens, *(f"{left}_{right}" for left, right in pairwise(tokens))]
        counts = Counter(features)
        vector = [0.0] * self.dimensions
        for feature, count in counts.items():
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, byteorder="big", signed=False)
            index = value % self.dimensions
            sign = -1.0 if value & (1 << 63) else 1.0
            weight = 1.25 if "_" in feature else 1.0
            vector[index] += sign * weight * (1.0 + math.log(count))
        norm = math.sqrt(sum(item * item for item in vector))
        if norm == 0:
            raise ValueError("cannot embed text without searchable terms")
        return [item / norm for item in vector]


class FastEmbedProvider:
    """Optional local semantic embedding provider backed by FastEmbed."""

    def __init__(
        self,
        *,
        model_name: str = "BAAI/bge-small-en-v1.5",
        dimensions: int = 384,
    ) -> None:
        try:
            fastembed = importlib.import_module("fastembed")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                'FastEmbed is optional; install ResolveOps with ".[embeddings]"'
            ) from exc
        model_class: Any = fastembed.TextEmbedding
        self.model: Any = model_class(model_name=model_name)
        self.model_name = model_name
        self._dimensions = dimensions

    @property
    def provider_name(self) -> str:
        return f"fastembed:{self.model_name}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = [item.tolist() for item in self.model.passage_embed(list(texts))]
        return self._validated(vectors)

    def embed_query(self, text: str) -> list[float]:
        vectors = [item.tolist() for item in self.model.query_embed(text)]
        if len(vectors) != 1:
            raise RuntimeError("embedding provider did not return one query vector")
        return self._validated(vectors)[0]

    def _validated(self, vectors: list[list[float]]) -> list[list[float]]:
        if any(len(vector) != self.dimensions for vector in vectors):
            raise RuntimeError("embedding model dimensions do not match configuration")
        return vectors
