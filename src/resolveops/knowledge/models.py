from enum import Enum
from math import isfinite
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from resolveops.models.case import CaseIssueType
from resolveops.models.common import (
    AwareDatetime,
    DomainModel,
    Identifier,
    NonEmptyText,
)

DocumentContent = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200_000),
]


class KnowledgeStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"


class RetrievalMethod(str, Enum):
    VECTOR = "vector"
    LEXICAL = "lexical"
    HYBRID = "hybrid"


class KnowledgeDocument(DomainModel):
    document_id: Identifier
    title: NonEmptyText
    version: int = Field(gt=0)
    status: KnowledgeStatus
    issue_types: list[CaseIssueType] = Field(min_length=1)
    source: NonEmptyText
    source_path: NonEmptyText
    effective_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    content: DocumentContent

    @property
    def version_id(self) -> str:
        return f"{self.document_id}:v{self.version}"

    @model_validator(mode="after")
    def validate_document(self) -> "KnowledgeDocument":
        if len(self.issue_types) != len(set(self.issue_types)):
            raise ValueError("knowledge document issue types must be unique")
        if self.expires_at is not None and self.expires_at <= self.effective_at:
            raise ValueError("expires_at must be later than effective_at")
        return self


class KnowledgeChunk(DomainModel):
    chunk_id: Identifier
    document_version_id: Identifier
    chunk_index: int = Field(ge=0)
    heading: NonEmptyText
    text: NonEmptyText
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ChunkEmbedding(DomainModel):
    chunk_id: Identifier
    provider_name: NonEmptyText
    dimensions: int = Field(gt=0)
    vector: list[float] = Field(min_length=1)
    embedded_at: AwareDatetime

    @model_validator(mode="after")
    def validate_vector(self) -> "ChunkEmbedding":
        if len(self.vector) != self.dimensions:
            raise ValueError("embedding vector length must match dimensions")
        if not all(isfinite(value) for value in self.vector):
            raise ValueError("embedding vector values must be finite")
        if not any(value != 0 for value in self.vector):
            raise ValueError("embedding vector cannot be all zeros")
        return self


class IngestionReport(DomainModel):
    discovered_documents: int = Field(ge=0)
    created_documents: int = Field(ge=0)
    skipped_documents: int = Field(ge=0)
    created_chunks: int = Field(ge=0)
    created_embeddings: int = Field(ge=0)
    skipped_embeddings: int = Field(ge=0)


class RetrievalResult(DomainModel):
    rank: int = Field(gt=0)
    score: float
    method: RetrievalMethod = RetrievalMethod.VECTOR
    chunk_id: Identifier
    document_id: Identifier
    document_version: int = Field(gt=0)
    title: NonEmptyText
    heading: NonEmptyText
    text: NonEmptyText
    source: NonEmptyText
    effective_at: AwareDatetime
    expires_at: AwareDatetime | None = None
    vector_rank: int | None = Field(default=None, gt=0)
    lexical_rank: int | None = Field(default=None, gt=0)
    vector_score: float | None = None
    lexical_score: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_scores(self) -> "RetrievalResult":
        scores = [self.score, self.vector_score, self.lexical_score]
        if any(value is not None and not isfinite(value) for value in scores):
            raise ValueError("retrieval scores must be finite")
        if self.method == RetrievalMethod.VECTOR and not -1.0 <= self.score <= 1.0:
            raise ValueError("vector score must be between -1 and 1")
        if self.method != RetrievalMethod.VECTOR and self.score < 0:
            raise ValueError("lexical and hybrid scores cannot be negative")
        return self


class RetrievalEvaluationCase(DomainModel):
    case_id: Identifier
    query: NonEmptyText
    issue_type: CaseIssueType | None = None
    relevant_document_ids: list[Identifier] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_relevance(self) -> "RetrievalEvaluationCase":
        if len(self.relevant_document_ids) != len(set(self.relevant_document_ids)):
            raise ValueError("relevant document IDs must be unique")
        return self


class RetrievalCaseResult(DomainModel):
    case_id: Identifier
    retrieved_document_ids: list[Identifier]
    recall_at_k: float = Field(ge=0, le=1)
    reciprocal_rank: float = Field(ge=0, le=1)
    ndcg_at_k: float = Field(ge=0, le=1)


class RetrievalMetrics(DomainModel):
    method: RetrievalMethod
    query_count: int = Field(gt=0)
    k: int = Field(gt=0)
    recall_at_k: float = Field(ge=0, le=1)
    mrr: float = Field(ge=0, le=1)
    ndcg_at_k: float = Field(ge=0, le=1)
    cases: list[RetrievalCaseResult]
