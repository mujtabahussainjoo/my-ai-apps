"""Embedding provider factory: the single place embedding providers are selected (TASK-018).

Selection is config-only via ``LLMConfig.embedding_provider`` (NFR-007, ACC-009). Every provider is
dimension-checked against the fixed schema dimension here, so a misconfigured or incompatible
embedding model fails at startup / on provider switch rather than at query time (FR-036).
"""

from __future__ import annotations

from ecommerce_support.core.config import EmbeddingProvider as EmbeddingProviderSetting
from ecommerce_support.core.config import LLMConfig, get_settings
from ecommerce_support.core.constants import EMBEDDING_DIMENSIONS
from ecommerce_support.core.exceptions import AppError, ConfigurationError, EmbeddingDimensionError
from ecommerce_support.core.readiness import CheckResult
from ecommerce_support.rag.embeddings.base import EmbeddingProvider
from ecommerce_support.rag.embeddings.mock import MockEmbeddingProvider
from ecommerce_support.rag.embeddings.ollama import OllamaEmbeddingProvider
from ecommerce_support.rag.embeddings.openai import OpenAIEmbeddingProvider

__all__ = [
    "check_embedding_dimensions",
    "create_embedding_provider",
    "validate_embedding_dimensions",
]


def create_embedding_provider(
    config: LLMConfig | None = None,
    *,
    expected_dimensions: int = EMBEDDING_DIMENSIONS,
) -> EmbeddingProvider:
    """Build the embedding provider selected by ``config`` and validate its dimension."""
    cfg = config or get_settings().llm
    provider = cfg.embedding_provider

    if provider is EmbeddingProviderSetting.mock:
        result: EmbeddingProvider = MockEmbeddingProvider(
            model=cfg.embedding_model or "mock-embedding",
            dimensions=cfg.embedding_dimensions,
        )
    elif provider is EmbeddingProviderSetting.openai:
        result = OpenAIEmbeddingProvider(
            model=cfg.embedding_model or "text-embedding-3-small",
            api_key=cfg.openai_api_key,
            base_url=cfg.openai_base_url,
            dimensions=cfg.embedding_dimensions,
        )
    elif provider is EmbeddingProviderSetting.ollama:
        result = OllamaEmbeddingProvider(
            model=cfg.ollama_embed_model,
            base_url=cfg.ollama_base_url,
            dimensions=cfg.embedding_dimensions,
        )
    elif provider is EmbeddingProviderSetting.huggingface:
        raise ConfigurationError(
            "HuggingFace embeddings are not supported by this build (no local model runtime).",
            details={"provider": provider.value},
        )
    else:  # pragma: no cover - enum is exhaustive; guards future additions
        raise ConfigurationError(
            f"Embedding provider {provider.value!r} is not implemented.",
            details={"provider": provider.value},
        )

    validate_embedding_dimensions(result, expected=expected_dimensions)
    return result


def validate_embedding_dimensions(
    provider: EmbeddingProvider, *, expected: int = EMBEDDING_DIMENSIONS
) -> None:
    """Fail loudly when a provider's dimension does not match the schema (FR-036)."""
    if provider.dimensions != expected:
        raise EmbeddingDimensionError(
            "Embedding dimension does not match the vector schema.",
            details={
                "provider": provider.name,
                "model": provider.model,
                "expected": expected,
                "configured": provider.dimensions,
            },
        )


async def check_embedding_dimensions() -> CheckResult:
    """Readiness check: the configured embedding provider matches the vector schema (FR-036)."""
    try:
        provider = create_embedding_provider()
    except AppError as exc:
        return CheckResult("embeddings", False, type(exc).__name__)
    await provider.aclose()
    return CheckResult("embeddings", True, f"{provider.name}:{provider.dimensions}")
