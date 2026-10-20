"""pgvector-backed chunk store (TASK-018; similarity search arrives in TASK-019).

A thin, typed wrapper over :class:`~ecommerce_support.db.repositories.document.DocumentRepository`
that enforces the fixed vector dimension at the storage boundary. Keeping it separate from the
repository leaves the repository free of vector-math concerns and gives retrieval (TASK-019) a
single seam to search through.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.core.constants import EMBEDDING_DIMENSIONS
from ecommerce_support.core.exceptions import EmbeddingDimensionError
from ecommerce_support.db.repositories.document import DocumentRepository
from ecommerce_support.schemas.documents import ChunkSearchHit, DocumentChunk

__all__ = ["PgVectorStore"]


class PgVectorStore:
    """Write and read path for chunk vectors (similarity search, TASK-019)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def replace_document_chunks(
        self,
        document_id: str,
        chunks: Sequence[DocumentChunk],
        embeddings: Sequence[list[float] | None] | None = None,
        *,
        expected_dimensions: int = EMBEDDING_DIMENSIONS,
    ) -> int:
        """Replace a document's chunks (and vectors), validating vector length first.

        Raises:
            EmbeddingDimensionError: a non-null vector's length differs from ``expected_dimensions``.
            ValueError: ``embeddings`` length does not match ``chunks``.
        """
        if embeddings is not None:
            self._validate_embeddings(embeddings, expected=expected_dimensions)
        return await DocumentRepository(self._session).replace_chunks(
            document_id, chunks, embeddings
        )

    async def search(
        self,
        embedding: Sequence[float],
        *,
        tenant_id: str = "default",
        metric: str = "cosine",
        limit: int = 5,
        filters: Mapping[str, str] | None = None,
        expected_dimensions: int = EMBEDDING_DIMENSIONS,
    ) -> list[ChunkSearchHit]:
        """Nearest-neighbor search, validating the query-vector dimension first (FR-036)."""
        if len(embedding) != expected_dimensions:
            raise EmbeddingDimensionError(
                "Query embedding length does not match the vector schema.",
                details={"expected": expected_dimensions, "received": len(embedding)},
            )
        return await DocumentRepository(self._session).search_chunks(
            embedding,
            tenant_id=tenant_id,
            metric=metric,
            limit=limit,
            filters=filters,
        )

    @staticmethod
    def _validate_embeddings(embeddings: Sequence[list[float] | None], *, expected: int) -> None:
        for index, vector in enumerate(embeddings):
            if vector is not None and len(vector) != expected:
                raise EmbeddingDimensionError(
                    "Refusing to store an embedding with the wrong dimension.",
                    details={"index": index, "expected": expected, "received": len(vector)},
                )
