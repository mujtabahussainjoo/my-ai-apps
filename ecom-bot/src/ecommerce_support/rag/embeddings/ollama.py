"""Ollama embeddings adapter over its HTTP API (TASK-018).

Ollama has no bundled Python SDK here, so we call ``/api/embed`` with an injectable ``httpx``
client (offline-testable). Only the batch endpoint is used; responses are validated by the base
class.
"""

from __future__ import annotations

from typing import Any

import httpx

from ecommerce_support.core.constants import EMBEDDING_DIMENSIONS
from ecommerce_support.core.exceptions import EmbeddingError
from ecommerce_support.rag.embeddings.base import EmbeddingProvider


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Ollama embeddings implementation of :class:`EmbeddingProvider`."""

    name = "ollama"

    def __init__(
        self,
        *,
        model: str = "nomic-embed-text",
        base_url: str = "http://localhost:11434",
        timeout: float | None = None,
        dimensions: int = EMBEDDING_DIMENSIONS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(model=model, dimensions=dimensions)
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await self._client.post(
                "/api/embed", json={"model": self.model, "input": list(texts)}
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
        except Exception as error:
            raise EmbeddingError(
                "Ollama embeddings request failed.",
                details={"provider": self.name, "error_type": type(error).__name__},
            ) from error
        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list):
            raise EmbeddingError(
                "Ollama embed response did not contain 'embeddings'.",
                details={"provider": self.name},
            )
        return [[float(value) for value in vector] for vector in embeddings]

    async def aclose(self) -> None:
        await self._client.aclose()
