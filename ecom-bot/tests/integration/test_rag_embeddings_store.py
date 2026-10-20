"""Integration tests for embedding persistence in pgvector (TASK-018).

Run against the compose database with migrations applied; skipped automatically when it is
unreachable. Each test runs inside a transaction that is rolled back.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.core.exceptions import EmbeddingDimensionError
from ecommerce_support.rag.embeddings.factory import create_embedding_provider
from ecommerce_support.rag.embeddings.mock import MockEmbeddingProvider
from ecommerce_support.rag.ingestion import ingest_document
from ecommerce_support.rag.loaders import LoadedDocument, load_document

pytestmark = pytest.mark.integration

_MARKDOWN = """\
# Returns

Items may be returned within 30 days of delivery.

# Shipping

Most orders ship within two business days.
"""


def _doc(source: str) -> LoadedDocument:
    return load_document(source=source, data=_MARKDOWN.encode(), filename="policy.md")


async def test_ingest_stores_dimensioned_embeddings(session: AsyncSession) -> None:
    source = f"policy-{uuid4()}.md"
    embedder = MockEmbeddingProvider()
    result = await ingest_document(session, _doc(source), embedder=embedder)

    rows = await session.execute(
        text(
            "SELECT vector_dims(embedding), count(*) "
            "FROM document_chunks WHERE document_id = :doc AND embedding IS NOT NULL "
            "GROUP BY vector_dims(embedding)"
        ),
        {"doc": result.document.id},
    )
    counts = dict(rows.all())
    assert counts == {1536: result.chunk_count}


async def test_factory_embedder_defaults_to_mock_and_indexes(session: AsyncSession) -> None:
    source = f"policy-{uuid4()}.md"
    embedder = create_embedding_provider()
    result = await ingest_document(session, _doc(source), embedder=embedder)
    stored = await session.scalar(
        text(
            "SELECT count(*) FROM document_chunks "
            "WHERE document_id = :doc AND embedding IS NOT NULL"
        ),
        {"doc": result.document.id},
    )
    assert int(stored) == result.chunk_count


async def test_dimension_mismatch_is_rejected(session: AsyncSession) -> None:
    source = f"policy-{uuid4()}.md"
    embedder = MockEmbeddingProvider(dimensions=8)
    with pytest.raises(EmbeddingDimensionError):
        await ingest_document(session, _doc(source), embedder=embedder)
