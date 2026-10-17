"""Policy document, chunk, and retrieval contracts for the RAG pipeline (FR-029-FR-034).

These are shared by ingestion/retrieval (``rag/``), tools, and the DB layer. No framework
imports; the vector store and embedder live behind their own interfaces.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from ecommerce_support.schemas.common import Schema
from ecommerce_support.schemas.enums import DocumentStatus


class PolicyDocument(Schema):
    """A versioned policy/FAQ document (DATA-006)."""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=300)
    source: str = Field(min_length=1, max_length=1000)
    version: int = Field(ge=1)
    content_hash: str = Field(min_length=1, max_length=128)
    status: DocumentStatus = DocumentStatus.PENDING
    chunk_count: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime | None = None


class DocumentChunk(Schema):
    """A chunk of a document version, with its embedding stored separately (FR-030)."""

    id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    content_hash: str = Field(min_length=1, max_length=128)
    section_title: str | None = Field(default=None, max_length=300)
    token_count: int | None = Field(default=None, ge=0)


class RetrievalQuery(Schema):
    """A retrieval request with metadata filters (FR-032)."""

    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=50)
    distance_threshold: float | None = Field(default=None, ge=0.0, le=2.0)
    filters: dict[str, str] = Field(default_factory=dict)


class RetrievalHit(Schema):
    """A single retrieved chunk with its similarity score."""

    chunk: DocumentChunk
    document_title: str = Field(min_length=1, max_length=300)
    score: float = Field(ge=0.0)


class RetrievalResult(Schema):
    """Retrieval outcome; ``abstained`` is True when no sufficient evidence (FR-034)."""

    query: str = Field(min_length=1)
    hits: list[RetrievalHit] = Field(default_factory=list)
    abstained: bool = False

    @property
    def is_empty(self) -> bool:
        """True when no chunks were retrieved."""
        return not self.hits
