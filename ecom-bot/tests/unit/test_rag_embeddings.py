"""Unit tests for embedding providers, factory, and dimension validation (TASK-018)."""

from __future__ import annotations

import math
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest

from ecommerce_support.core.config import LLMConfig
from ecommerce_support.core.constants import EMBEDDING_DIMENSIONS
from ecommerce_support.core.exceptions import (
    ConfigurationError,
    EmbeddingDimensionError,
    EmbeddingError,
)
from ecommerce_support.rag.embeddings.base import EmbeddingProvider
from ecommerce_support.rag.embeddings.factory import (
    create_embedding_provider,
    validate_embedding_dimensions,
)
from ecommerce_support.rag.embeddings.mock import MockEmbeddingProvider
from ecommerce_support.rag.embeddings.ollama import OllamaEmbeddingProvider
from ecommerce_support.rag.embeddings.openai import OpenAIEmbeddingProvider
from ecommerce_support.rag.store import PgVectorStore


class _DroppingProvider(EmbeddingProvider):
    name = "dropping"

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self.dimensions for _ in texts[:-1]]


class _WrongDimProvider(EmbeddingProvider):
    name = "wrong-dim"

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * (self.dimensions - 1) for _ in texts]


class _FakeEmbeddingsAPI:
    def __init__(self, items: list[SimpleNamespace], *, fail: bool = False) -> None:
        self._items = items
        self._fail = fail

    async def create(self, *, model: str, input: list[str]) -> Any:
        if self._fail:
            raise RuntimeError("nope")
        return SimpleNamespace(data=list(self._items))


def _openai_provider(
    items: list[SimpleNamespace], *, fail: bool = False
) -> OpenAIEmbeddingProvider:
    fake = SimpleNamespace(embeddings=_FakeEmbeddingsAPI(items, fail=fail))
    dimensions = len(items[0].embedding) if items else 3
    return OpenAIEmbeddingProvider(model="m", dimensions=dimensions, client=cast(Any, fake))


def _ollama_provider(handler: Any) -> OllamaEmbeddingProvider:
    transport = httpx.MockTransport(handler)
    return OllamaEmbeddingProvider(
        model="nomic-embed-text",
        dimensions=3,
        client=httpx.AsyncClient(transport=transport, base_url="http://ollama"),
    )


# --- mock provider ----------------------------------------------------------


async def test_mock_provider_is_deterministic() -> None:
    provider = MockEmbeddingProvider(dimensions=8)
    assert await provider.embed_one("returns") == await provider.embed_one("returns")


async def test_mock_provider_distinct_texts_differ() -> None:
    provider = MockEmbeddingProvider(dimensions=8)
    assert await provider.embed_one("a") != await provider.embed_one("b")


async def test_mock_vector_is_unit_norm() -> None:
    vector = await MockEmbeddingProvider(dimensions=16).embed_one("anything")
    assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0, rel_tol=1e-6)


def test_mock_defaults_to_schema_dimension() -> None:
    assert MockEmbeddingProvider().dimensions == EMBEDDING_DIMENSIONS


async def test_embed_batch_preserves_order() -> None:
    provider = MockEmbeddingProvider(dimensions=4)
    vectors = await provider.embed(["one", "two", "three"])
    assert vectors[0] == await provider.embed_one("one")
    assert vectors[2] == await provider.embed_one("three")


async def test_embed_empty_batch_returns_empty() -> None:
    assert await MockEmbeddingProvider(dimensions=4).embed([]) == []


async def test_provider_requires_model_name() -> None:
    with pytest.raises(ConfigurationError):
        MockEmbeddingProvider(model="")


# --- base batch validation --------------------------------------------------


async def test_wrong_number_of_vectors_rejected() -> None:
    with pytest.raises(EmbeddingDimensionError, match="number of vectors"):
        await _DroppingProvider(model="m", dimensions=4).embed(["a", "b"])


async def test_wrong_vector_length_rejected() -> None:
    with pytest.raises(EmbeddingDimensionError, match="length"):
        await _WrongDimProvider(model="m", dimensions=4).embed(["a"])


# --- factory ----------------------------------------------------------------


def test_factory_defaults_to_mock() -> None:
    provider = create_embedding_provider(LLMConfig())
    assert isinstance(provider, MockEmbeddingProvider)
    assert provider.dimensions == EMBEDDING_DIMENSIONS


def test_factory_openai_requires_key() -> None:
    config = LLMConfig(embedding_provider="openai", openai_api_key=None)
    with pytest.raises(ConfigurationError, match="API key"):
        create_embedding_provider(config)


def test_factory_openai_with_key_builds_provider() -> None:
    config = LLMConfig(embedding_provider="openai", openai_api_key="sk-test")
    provider = create_embedding_provider(config)
    assert provider.name == "openai"
    assert provider.dimensions == EMBEDDING_DIMENSIONS


def test_factory_ollama_builds_provider() -> None:
    assert create_embedding_provider(LLMConfig(embedding_provider="ollama")).name == "ollama"


def test_factory_huggingface_fails_loudly() -> None:
    with pytest.raises(ConfigurationError, match="HuggingFace"):
        create_embedding_provider(LLMConfig(embedding_provider="huggingface"))


def test_factory_rejects_dimension_mismatch() -> None:
    with pytest.raises(EmbeddingDimensionError):
        create_embedding_provider(LLMConfig(embedding_dimensions=8))


def test_validate_dimensions_helper() -> None:
    provider = MockEmbeddingProvider(dimensions=8)
    with pytest.raises(EmbeddingDimensionError):
        validate_embedding_dimensions(provider, expected=EMBEDDING_DIMENSIONS)
    validate_embedding_dimensions(provider, expected=8)


# --- openai adapter ---------------------------------------------------------


async def test_openai_adapter_reorders_by_index() -> None:
    items = [
        SimpleNamespace(index=1, embedding=[0.0, 1.0, 0.0]),
        SimpleNamespace(index=0, embedding=[1.0, 0.0, 0.0]),
    ]
    provider = _openai_provider(items)
    assert await provider.embed(["a", "b"]) == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]


async def test_openai_adapter_wraps_errors() -> None:
    provider = _openai_provider([SimpleNamespace(index=0, embedding=[0.0, 0.0, 0.0])], fail=True)
    with pytest.raises(EmbeddingError):
        await provider.embed(["a"])


# --- ollama adapter ---------------------------------------------------------


async def test_ollama_adapter_parses_embeddings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]})

    assert await _ollama_provider(handler).embed(["a", "b"]) == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]


async def test_ollama_adapter_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(EmbeddingError):
        await _ollama_provider(handler).embed(["a"])


async def test_ollama_adapter_missing_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    with pytest.raises(EmbeddingError, match="embeddings"):
        await _ollama_provider(handler).embed(["a"])


# --- store dimension guard --------------------------------------------------


def test_store_rejects_wrong_dimension() -> None:
    with pytest.raises(EmbeddingDimensionError):
        PgVectorStore._validate_embeddings([[0.0, 1.0]], expected=EMBEDDING_DIMENSIONS)


def test_store_allows_none_and_correct_vectors() -> None:
    PgVectorStore._validate_embeddings(
        [None, [0.0] * EMBEDDING_DIMENSIONS], expected=EMBEDDING_DIMENSIONS
    )
