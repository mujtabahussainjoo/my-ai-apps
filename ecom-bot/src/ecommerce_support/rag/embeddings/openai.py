"""OpenAI embeddings adapter (TASK-018).

The only embeddings module that imports the OpenAI SDK. Errors are normalized to
:class:`EmbeddingError` at the boundary; response vectors are validated by the base class.
"""

from __future__ import annotations

from openai import AsyncOpenAI

from ecommerce_support.core.constants import EMBEDDING_DIMENSIONS
from ecommerce_support.core.exceptions import ConfigurationError, EmbeddingError
from ecommerce_support.rag.embeddings.base import EmbeddingProvider


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI Embeddings API implementation of :class:`EmbeddingProvider`."""

    name = "openai"

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        dimensions: int = EMBEDDING_DIMENSIONS,
        client: AsyncOpenAI | None = None,
    ) -> None:
        super().__init__(model=model, dimensions=dimensions)
        if client is None:
            if not api_key:
                raise ConfigurationError(
                    "OpenAI embeddings require an API key (set LLM__OPENAI_API_KEY)."
                )
            client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        self._client = client

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await self._client.embeddings.create(model=self.model, input=texts)
        except Exception as error:
            raise EmbeddingError(
                "OpenAI embedding request failed.",
                details={"provider": self.name, "error_type": type(error).__name__},
            ) from error
        ordered = sorted(response.data, key=lambda item: item.index)
        return [list(item.embedding) for item in ordered]

    async def aclose(self) -> None:
        await self._client.close()
