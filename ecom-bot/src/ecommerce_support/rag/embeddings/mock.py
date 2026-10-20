"""Deterministic in-process embedding provider for tests and offline mode (TASK-018).

Produces unit-norm vectors derived purely from a SHA-256 expansion of the input text — no network,
no model weights, no credentials. Identical text always yields the identical vector, which makes
retrieval-ordering tests reproducible.
"""

from __future__ import annotations

import hashlib
import math

from ecommerce_support.core.constants import EMBEDDING_DIMENSIONS
from ecommerce_support.rag.embeddings.base import EmbeddingProvider

_BYTES_PER_FLOAT = 4


class MockEmbeddingProvider(EmbeddingProvider):
    """Deterministic, offline :class:`EmbeddingProvider`."""

    name = "mock"

    def __init__(
        self, *, model: str = "mock-embedding", dimensions: int = EMBEDDING_DIMENSIONS
    ) -> None:
        super().__init__(model=model, dimensions=dimensions)

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        values: list[float] = []
        counter = 0
        while len(values) < self.dimensions:
            digest = hashlib.sha256(text.encode("utf-8") + counter.to_bytes(4, "big")).digest()
            for offset in range(0, len(digest), _BYTES_PER_FLOAT):
                if len(values) >= self.dimensions:
                    break
                raw = int.from_bytes(digest[offset : offset + _BYTES_PER_FLOAT], "big")
                values.append((raw / 0xFFFFFFFF) * 2.0 - 1.0)
            counter += 1
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]
