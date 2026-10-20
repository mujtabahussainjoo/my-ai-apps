"""Unit tests for threshold, score mapping, rerank, and the Retriever (TASK-019)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

from ecommerce_support.core.exceptions import ValidationError
from ecommerce_support.rag.embeddings.mock import MockEmbeddingProvider
from ecommerce_support.rag.rerank import LexicalReranker
from ecommerce_support.rag.retrieval import Retriever, apply_threshold, similarity_from_distance
from ecommerce_support.schemas.documents import (
    ChunkSearchHit,
    DocumentChunk,
    RetrievalQuery,
)


def _hit(
    content: str, distance: float, index: int = 0, title: str = "Refund Policy"
) -> ChunkSearchHit:
    return ChunkSearchHit(
        chunk=DocumentChunk(
            id=f"chk-{index}",
            document_id="doc-1",
            version=1,
            chunk_index=index,
            content=content,
            content_hash=f"hash-{index}",
        ),
        document_title=title,
        distance=distance,
    )


class FakeSearcher:
    def __init__(self, hits: list[ChunkSearchHit]) -> None:
        self._hits = hits
        self.calls: list[dict[str, object]] = []

    async def search(
        self,
        embedding: Sequence[float],
        *,
        tenant_id: str = "default",
        metric: str = "cosine",
        limit: int = 5,
        filters: Mapping[str, str] | None = None,
    ) -> list[ChunkSearchHit]:
        self.calls.append(
            {
                "embedding_len": len(embedding),
                "tenant_id": tenant_id,
                "metric": metric,
                "limit": limit,
                "filters": dict(filters or {}),
            }
        )
        return list(self._hits)[:limit]


# --- score mapping ----------------------------------------------------------


def test_cosine_similarity() -> None:
    assert similarity_from_distance("cosine", 0.0) == 1.0
    assert similarity_from_distance("cosine", 0.35) == pytest.approx(0.65)


def test_l2_similarity_is_bounded() -> None:
    assert similarity_from_distance("l2", 0.0) == 1.0
    assert 0.0 < similarity_from_distance("l2", 3.0) < 1.0


def test_ip_similarity_is_bounded() -> None:
    assert similarity_from_distance("ip", -1.0) == 1.0
    assert similarity_from_distance("ip", 1.0) == 0.0


def test_similarity_never_negative() -> None:
    assert similarity_from_distance("cosine", 2.0) == 0.0


# --- threshold --------------------------------------------------------------


def test_apply_threshold_keeps_near_hits() -> None:
    hits = [_hit("a", 0.1), _hit("b", 0.5), _hit("c", 0.3)]
    kept = apply_threshold(hits, 0.35)
    assert [hit.chunk.content for hit in kept] == ["a", "c"]


def test_apply_threshold_none_disables_filtering() -> None:
    hits = [_hit("a", 0.1), _hit("b", 1.5)]
    assert apply_threshold(hits, None) == hits


# --- lexical reranker -------------------------------------------------------


def test_lexical_reranker_prefers_query_coverage() -> None:
    hits = [_hit("shipping delays", 0.1, 0), _hit("refund thirty days", 0.2, 1)]
    reranked = LexicalReranker().rerank("refund window", hits, top_n=2)
    assert reranked[0].chunk.content == "refund thirty days"


def test_lexical_reranker_limits_to_top_n() -> None:
    hits = [_hit("a refund", 0.1, 0), _hit("refund b", 0.2, 1), _hit("refund c", 0.3, 2)]
    assert len(LexicalReranker().rerank("refund", hits, top_n=2)) == 2


# --- Retriever --------------------------------------------------------------


async def test_retriever_returns_thresholded_hits() -> None:
    searcher = FakeSearcher([_hit("close", 0.1, 0), _hit("far", 0.9, 1)])
    retriever = Retriever(
        embedder=MockEmbeddingProvider(dimensions=4),
        store=searcher,
        top_k=5,
        distance_threshold=0.35,
    )
    result = await retriever.retrieve("refund policy")
    assert result.abstained is False
    assert [hit.chunk.content for hit in result.hits] == ["close"]
    assert result.hits[0].score == pytest.approx(0.9)
    assert searcher.calls[0]["tenant_id"] == "default"
    assert searcher.calls[0]["embedding_len"] == 4


async def test_retriever_abstains_when_all_far() -> None:
    searcher = FakeSearcher([_hit("far", 0.9)])
    retriever = Retriever(embedder=MockEmbeddingProvider(dimensions=4), store=searcher)
    result = await retriever.retrieve("anything")
    assert result.abstained is True
    assert result.hits == []


async def test_retriever_honors_query_overrides() -> None:
    searcher = FakeSearcher([_hit("a", 0.1, 0), _hit("b", 0.2, 1), _hit("c", 0.3, 2)])
    retriever = Retriever(embedder=MockEmbeddingProvider(dimensions=4), store=searcher)
    request = RetrievalQuery(query="q", top_k=2, distance_threshold=0.25, filters={"source": "x"})
    result = await retriever.retrieve(request)
    assert len(result.hits) == 2
    assert searcher.calls[0]["filters"] == {"source": "x"}
    assert searcher.calls[0]["limit"] == 2


async def test_retriever_rejects_empty_query() -> None:
    retriever = Retriever(embedder=MockEmbeddingProvider(dimensions=4), store=FakeSearcher([]))
    with pytest.raises(ValidationError):
        await retriever.retrieve("   ")


async def test_retriever_applies_rerank_and_widens_candidates() -> None:
    searcher = FakeSearcher(
        [_hit("shipping only", 0.05, 0), _hit("refund within thirty days", 0.20, 1)]
    )
    retriever = Retriever(
        embedder=MockEmbeddingProvider(dimensions=4),
        store=searcher,
        top_k=1,
        distance_threshold=0.35,
        rerank_enabled=True,
        rerank_top_n=5,
    )
    result = await retriever.retrieve("refund")
    assert searcher.calls[0]["limit"] == 5
    assert result.hits[0].chunk.content == "refund within thirty days"
