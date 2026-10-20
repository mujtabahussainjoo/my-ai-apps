"""Semantic retrieval over indexed policy chunks (TASK-019, FR-031-FR-034).

Pipeline: normalize query → embed (dimension-checked) → vector search (tenant + metadata filters)
→ apply distance threshold → optional rerank → bounded similarity scores. Only evidence that
survives the threshold is returned; when nothing survives, the result is ``abstained`` so the
caller clarifies/escalates instead of guessing (FR-034).

The vector search itself lives in the repository/vector-store layer; this module owns the
policy decisions (threshold, rerank, score) and is framework-free.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.core.config import RagConfig, get_settings
from ecommerce_support.core.exceptions import ValidationError
from ecommerce_support.rag.embeddings.base import EmbeddingProvider
from ecommerce_support.rag.normalization import normalize_text
from ecommerce_support.rag.rerank import LexicalReranker, Reranker
from ecommerce_support.rag.store import PgVectorStore
from ecommerce_support.schemas.documents import (
    ChunkSearchHit,
    RetrievalHit,
    RetrievalQuery,
    RetrievalResult,
)

__all__ = [
    "Retriever",
    "VectorSearcher",
    "apply_threshold",
    "create_retriever",
    "similarity_from_distance",
]


class VectorSearcher(Protocol):
    """Structural type for the vector store's read path (dependency injection for tests)."""

    async def search(
        self,
        embedding: Sequence[float],
        *,
        tenant_id: str = ...,
        metric: str = ...,
        limit: int = ...,
        filters: Mapping[str, str] | None = ...,
    ) -> list[ChunkSearchHit]: ...


def similarity_from_distance(metric: str, distance: float) -> float:
    """Map a raw pgvector distance to a bounded ``[0, 1]`` similarity score (higher is better)."""
    if metric == "l2":
        score = 1.0 / (1.0 + max(0.0, distance))
    elif metric == "ip":
        score = (-distance + 1.0) / 2.0
    else:  # cosine
        score = 1.0 - distance
    return max(0.0, min(1.0, score))


def apply_threshold(
    hits: Sequence[ChunkSearchHit], threshold: float | None
) -> list[ChunkSearchHit]:
    """Keep only hits within ``threshold`` distance; ``None`` disables thresholding (FR-034)."""
    if threshold is None:
        return list(hits)
    return [hit for hit in hits if hit.distance <= threshold]


class Retriever:
    """Thresholded, optionally reranked semantic retrieval over the policy vector store."""

    def __init__(
        self,
        *,
        embedder: EmbeddingProvider,
        store: VectorSearcher,
        top_k: int = 5,
        distance_threshold: float | None = 0.35,
        distance_metric: str = "cosine",
        rerank_enabled: bool = False,
        rerank_top_n: int = 5,
        reranker: Reranker | None = None,
    ) -> None:
        self._embedder = embedder
        self._store = store
        self._top_k = top_k
        self._distance_threshold = distance_threshold
        self._distance_metric = distance_metric
        self._rerank_enabled = rerank_enabled
        self._rerank_top_n = rerank_top_n
        self._reranker: Reranker = reranker or LexicalReranker()

    @classmethod
    def from_session(
        cls,
        session: AsyncSession,
        embedder: EmbeddingProvider,
        config: RagConfig | None = None,
        *,
        reranker: Reranker | None = None,
    ) -> Retriever:
        """Build a retriever from configuration (``config/rag.yaml`` defaults)."""
        cfg = config or get_settings().rag
        return cls(
            embedder=embedder,
            store=PgVectorStore(session),
            top_k=cfg.top_k,
            distance_threshold=cfg.distance_threshold,
            distance_metric=cfg.distance_metric,
            rerank_enabled=cfg.rerank_enabled,
            rerank_top_n=cfg.rerank_top_n,
            reranker=reranker,
        )

    async def retrieve(
        self, query: str | RetrievalQuery, *, tenant_id: str = "default"
    ) -> RetrievalResult:
        """Retrieve evidence for ``query``, abstaining when nothing clears the threshold."""
        request = self._as_request(query)
        normalized = normalize_text(request.query)
        if not normalized:
            return RetrievalResult(query=request.query, hits=[], abstained=True)

        vector = await self._embedder.embed_one(normalized)
        candidates = await self._store.search(
            vector,
            tenant_id=tenant_id,
            metric=self._distance_metric,
            limit=self._candidate_limit(request.top_k),
            filters=request.filters,
        )
        survivors = apply_threshold(candidates, request.distance_threshold)
        if self._rerank_enabled and survivors:
            survivors = self._reranker.rerank(
                normalized, survivors, top_n=min(self._rerank_top_n, request.top_k)
            )
        hits = [
            RetrievalHit(
                chunk=hit.chunk,
                document_title=hit.document_title,
                score=similarity_from_distance(self._distance_metric, hit.distance),
            )
            for hit in survivors[: request.top_k]
        ]
        return RetrievalResult(query=request.query, hits=hits, abstained=not hits)

    # -- internals ---------------------------------------------------------

    def _as_request(self, query: str | RetrievalQuery) -> RetrievalQuery:
        if isinstance(query, RetrievalQuery):
            return query
        if not query or not query.strip():
            raise ValidationError("Retrieval query must not be empty.", details={})
        return RetrievalQuery(
            query=query,
            top_k=self._top_k,
            distance_threshold=self._distance_threshold,
        )

    def _candidate_limit(self, top_k: int) -> int:
        if self._rerank_enabled:
            return max(top_k, self._rerank_top_n)
        return top_k


def create_retriever(
    session: AsyncSession,
    embedder: EmbeddingProvider,
    config: RagConfig | None = None,
    *,
    reranker: Reranker | None = None,
) -> Retriever:
    """Convenience wrapper around :meth:`Retriever.from_session`."""
    return Retriever.from_session(session, embedder, config, reranker=reranker)
