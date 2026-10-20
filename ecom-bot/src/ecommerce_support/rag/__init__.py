"""RAG pipeline: load, normalize, chunk, embed, store, retrieve, rerank, cite, abstain.

Phase 5. TASK-016 provides document loading, type/size validation, and text normalization;
TASK-017 adds deterministic chunking, content-hash dedupe, and versioned ingestion tracking;
TASK-018 adds embeddings and pgvector persistence; TASK-019 adds thresholded retrieval,
metadata filtering, and optional reranking; TASK-020 adds grounded, cited generation with
abstention.
"""

from __future__ import annotations

from ecommerce_support.rag.chunking import (
    ChunkDraft,
    Section,
    chunk_text,
    estimate_tokens,
    split_sections,
)
from ecommerce_support.rag.embeddings import (
    EMBEDDING_DIMENSIONS,
    EmbeddingProvider,
    MockEmbeddingProvider,
    create_embedding_provider,
    validate_embedding_dimensions,
)
from ecommerce_support.rag.generation import (
    ABSTAIN_MESSAGE,
    GroundedGenerator,
    create_grounded_generator,
)
from ecommerce_support.rag.hashing import content_hash
from ecommerce_support.rag.ingestion import (
    IngestionResult,
    ingest_document,
    mark_ingestion_failed,
)
from ecommerce_support.rag.loaders import (
    DEFAULT_MAX_DOCUMENT_BYTES,
    EXTENSION_TYPES,
    MEDIA_TYPE_TYPES,
    SUPPORTED_DOCUMENT_TYPES,
    DocumentType,
    LoadedDocument,
    detect_document_type,
    load_document,
)
from ecommerce_support.rag.normalization import markdown_to_text, normalize_text
from ecommerce_support.rag.rerank import LexicalReranker, Reranker
from ecommerce_support.rag.retrieval import (
    Retriever,
    apply_threshold,
    create_retriever,
    similarity_from_distance,
)
from ecommerce_support.rag.store import PgVectorStore

__all__ = [
    "ABSTAIN_MESSAGE",
    "DEFAULT_MAX_DOCUMENT_BYTES",
    "EMBEDDING_DIMENSIONS",
    "EXTENSION_TYPES",
    "MEDIA_TYPE_TYPES",
    "SUPPORTED_DOCUMENT_TYPES",
    "ChunkDraft",
    "DocumentType",
    "EmbeddingProvider",
    "GroundedGenerator",
    "IngestionResult",
    "LexicalReranker",
    "LoadedDocument",
    "MockEmbeddingProvider",
    "PgVectorStore",
    "Reranker",
    "Retriever",
    "Section",
    "apply_threshold",
    "chunk_text",
    "content_hash",
    "create_embedding_provider",
    "create_grounded_generator",
    "create_retriever",
    "detect_document_type",
    "estimate_tokens",
    "ingest_document",
    "load_document",
    "mark_ingestion_failed",
    "markdown_to_text",
    "normalize_text",
    "similarity_from_distance",
    "split_sections",
    "validate_embedding_dimensions",
]
