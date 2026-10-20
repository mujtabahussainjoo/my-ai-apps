"""Embedding provider contract (TASK-018, FR-036).

Embeddings are provider-neutral like the LLM layer: business code depends on this ABC, and the
factory in :mod:`ecommerce_support.rag.embeddings.factory` selects the concrete provider from
configuration. Every vector's length is validated against the provider's declared dimension and
the fixed schema dimension, so a mismatch fails loudly instead of corrupting the vector index.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from ecommerce_support.core.constants import EMBEDDING_DIMENSIONS
from ecommerce_support.core.exceptions import ConfigurationError, EmbeddingDimensionError

__all__ = ["EMBEDDING_DIMENSIONS", "EmbeddingProvider"]


class EmbeddingProvider(ABC):
    """An async embedding provider that turns text into fixed-dimension vectors."""

    name: str = "base"

    def __init__(self, *, model: str, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        if not model:
            raise ConfigurationError("Embedding provider requires a model name.")
        if dimensions <= 0:
            raise ConfigurationError("Embedding dimensions must be positive.")
        self.model = model
        self.dimensions = dimensions

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed ``texts`` in order, validating the batch shape before returning."""
        items = list(texts)
        if not items:
            return []
        vectors = await self._embed(items)
        self._validate_batch(vectors, expected=len(items))
        return vectors

    async def embed_one(self, text: str) -> list[float]:
        """Embed a single string and return its vector."""
        vectors = await self.embed([text])
        return vectors[0]

    @abstractmethod
    async def _embed(self, texts: list[str]) -> list[list[float]]:
        """Provider-specific batch embedding; may raise :class:`EmbeddingError`."""

    async def aclose(self) -> None:
        """Release provider resources (no-op by default)."""
        return None

    def _validate_batch(self, vectors: Sequence[Sequence[float]], *, expected: int) -> None:
        if len(vectors) != expected:
            raise EmbeddingDimensionError(
                "Embedding provider returned the wrong number of vectors.",
                details={
                    "provider": self.name,
                    "expected": expected,
                    "received": len(vectors),
                },
            )
        for index, vector in enumerate(vectors):
            if len(vector) != self.dimensions:
                raise EmbeddingDimensionError(
                    "Embedding vector length does not match the configured dimension.",
                    details={
                        "provider": self.name,
                        "index": index,
                        "expected": self.dimensions,
                        "received": len(vector),
                    },
                )
