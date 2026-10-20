"""Policy document, chunk, and retrieval contracts for the RAG pipeline (FR-029-FR-034).

These are shared by ingestion/retrieval (``rag/``), tools, and the DB layer. No framework
imports; the vector store and embedder live behind their own interfaces.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from ecommerce_support.schemas.agents import SourceCitation
from ecommerce_support.schemas.common import Schema
from ecommerce_support.schemas.enums import DocumentStatus

# Mirrors LIMITS config default (max_document_bytes); the service enforces the configured cap.
MAX_INGEST_BYTES = 10 * 1024 * 1024

_MAX_TITLE = 300


class DocumentIngestRequest(Schema):
    """A policy/knowledge document to ingest (FR-029).

    Text is supplied inline; ``source`` is the stable identity used for versioning/dedupe
    (a URL, path, or logical name). Binary upload handling arrives with the ingestion API work.
    """

    source: str = Field(min_length=1, max_length=1000)
    content: str = Field(min_length=1, max_length=MAX_INGEST_BYTES)
    title: str | None = Field(default=None, max_length=_MAX_TITLE)
    media_type: str = Field(default="text/plain", min_length=1, max_length=100)


class PolicyDocument(Schema):
    """A versioned policy/FAQ document (DATA-006)."""

    id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=300)
    source: str = Field(min_length=1, max_length=1000)
    version: int = Field(ge=1)
    content_hash: str = Field(min_length=1, max_length=128)
    status: DocumentStatus = DocumentStatus.PENDING
    chunk_count: int = Field(default=0, ge=0)
    error_message: str | None = None
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


class ChunkSearchHit(Schema):
    """A raw vector-search result: the chunk, its document title, and the distance metric value.

    ``distance`` is the raw pgvector distance (smaller is more similar); the retrieval layer
    converts it to a bounded ``score`` and applies the threshold.
    """

    chunk: DocumentChunk
    document_title: str = Field(min_length=1, max_length=300)
    distance: float


class RetrievalResult(Schema):
    """Retrieval outcome; ``abstained`` is True when no sufficient evidence (FR-034)."""

    query: str = Field(min_length=1)
    hits: list[RetrievalHit] = Field(default_factory=list)
    abstained: bool = False

    @property
    def is_empty(self) -> bool:
        """True when no chunks were retrieved."""
        return not self.hits


class GroundedAnswer(Schema):
    """A policy answer grounded in retrieved evidence, with citations (FR-033/FR-034).

    ``abstained`` is True when no trusted evidence was available; ``reason`` records why
    (``no_evidence``, ``untrusted_evidence``, ``empty_generation``).
    """

    query: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    citations: list[SourceCitation] = Field(default_factory=list)
    abstained: bool = False
    reason: str = ""
