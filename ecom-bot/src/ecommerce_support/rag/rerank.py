"""Optional reranking for retrieved chunks (TASK-019, FR-032).

The default reranker is lexical (token overlap) and fully offline — no cross-encoder weights are
bundled. It is intentionally behind a small :class:`Reranker` protocol so a neural cross-encoder
can be dropped in later without touching retrieval. Reranking is off by default
(``rag.rerank_enabled=false``).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol

from ecommerce_support.schemas.documents import ChunkSearchHit

__all__ = ["LexicalReranker", "Reranker"]

_WORD = re.compile(r"[a-z0-9]+")


class Reranker(Protocol):
    """Reorders candidate chunks by relevance to the query, keeping the best ``top_n``."""

    def rerank(
        self, query: str, hits: Sequence[ChunkSearchHit], *, top_n: int
    ) -> list[ChunkSearchHit]: ...


class LexicalReranker:
    """Deterministic lexical reranker based on query-token coverage (offline, no model)."""

    name = "lexical"

    def rerank(
        self, query: str, hits: Sequence[ChunkSearchHit], *, top_n: int
    ) -> list[ChunkSearchHit]:
        tokens = _tokens(query)
        if not tokens:
            return list(hits[:top_n])
        unique = set(tokens)
        ranked = sorted(
            hits,
            key=lambda hit: self._coverage(unique, hit.chunk.content),
            reverse=True,
        )
        return ranked[:top_n]

    @staticmethod
    def _coverage(query_tokens: set[str], content: str) -> float:
        if not query_tokens:
            return 0.0
        content_tokens = set(_tokens(content))
        return len(query_tokens & content_tokens) / len(query_tokens)


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())
