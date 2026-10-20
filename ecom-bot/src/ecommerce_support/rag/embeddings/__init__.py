"""Embedding providers for RAG ingestion/retrieval (TASK-018, FR-036)."""

from __future__ import annotations

from ecommerce_support.rag.embeddings.base import EMBEDDING_DIMENSIONS, EmbeddingProvider
from ecommerce_support.rag.embeddings.factory import (
    create_embedding_provider,
    validate_embedding_dimensions,
)
from ecommerce_support.rag.embeddings.mock import MockEmbeddingProvider

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "EmbeddingProvider",
    "MockEmbeddingProvider",
    "create_embedding_provider",
    "validate_embedding_dimensions",
]
