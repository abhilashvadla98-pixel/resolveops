# ADR-004: Exact hybrid policy retrieval

## Context

The policy corpus is small, versioned, and contains terminology where exact words and semantic
similarity both matter.

## Decision

Use heading-aware chunks, BM25 lexical ranking, exact cosine vector ranking, and reciprocal-rank
fusion. Preserve document/version/source metadata with every result.

## Alternatives considered

- Vector search only: weaker on exact identifiers and policy terminology in the baseline.
- GraphRAG or a separate vector service: rejected because the corpus does not justify their cost.
- Cross-encoder reranking: defer until measured hard negatives show a need.

## Consequences

Retrieval is inspectable and easy to reproduce. Exact vector search will need replacement if corpus
size makes its measured latency unacceptable.
