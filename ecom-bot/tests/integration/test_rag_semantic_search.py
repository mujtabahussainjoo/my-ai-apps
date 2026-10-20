"""Integration tests for semantic retrieval over pgvector (TASK-019).

Run against the compose database with migrations applied (`make db-up && make migrate`);
skipped automatically when it is unreachable. Each test runs inside a transaction that is
rolled back, so no rows persist.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.core.config import RagConfig
from ecommerce_support.core.exceptions import ValidationError
from ecommerce_support.rag.embeddings.mock import MockEmbeddingProvider
from ecommerce_support.rag.ingestion import ingest_document
from ecommerce_support.rag.loaders import load_document
from ecommerce_support.rag.retrieval import Retriever

pytestmark = pytest.mark.integration

_CHUNK_TEXT = "Refund window is thirty days from delivery."


async def _ingest(session: AsyncSession, text: str = _CHUNK_TEXT) -> str:
    source = f"policy-{uuid4()}.md"
    loaded = load_document(source=source, data=text.encode(), filename="policy.md")
    result = await ingest_document(
        session, loaded, embedder=MockEmbeddingProvider(), chunk_size=1000, chunk_overlap=0
    )
    return result.document.id


def _retriever(session: AsyncSession) -> Retriever:
    return Retriever.from_session(session, MockEmbeddingProvider(), RagConfig())


async def test_retrieves_exact_match(session: AsyncSession) -> None:
    await _ingest(session)
    result = await _retriever(session).retrieve(_CHUNK_TEXT)
    assert result.abstained is False
    assert result.hits[0].chunk.content == _CHUNK_TEXT
    assert result.hits[0].score == pytest.approx(1.0, abs=1e-3)


async def test_abstains_on_unrelated_query(session: AsyncSession) -> None:
    await _ingest(session)
    result = await _retriever(session).retrieve("how do I pay with cryptocurrency")
    assert result.abstained is True
    assert result.hits == []


async def test_metadata_filter_by_document_id(session: AsyncSession) -> None:
    document_id = await _ingest(session)
    from ecommerce_support.schemas.documents import RetrievalQuery

    retriever = _retriever(session)
    hit = await retriever.retrieve(
        RetrievalQuery(query=_CHUNK_TEXT, filters={"document_id": document_id})
    )
    assert hit.abstained is False

    other = await retriever.retrieve(
        RetrievalQuery(query=_CHUNK_TEXT, filters={"document_id": "doc_does_not_exist"})
    )
    assert other.abstained is True


async def test_unknown_filter_fails_loudly(session: AsyncSession) -> None:
    await _ingest(session)
    from ecommerce_support.schemas.documents import RetrievalQuery

    with pytest.raises(ValidationError, match="filter"):
        await _retriever(session).retrieve(
            RetrievalQuery(query=_CHUNK_TEXT, filters={"nonsense": "x"})
        )


async def test_tenant_isolation(session: AsyncSession) -> None:
    await _ingest(session)
    result = await _retriever(session).retrieve(_CHUNK_TEXT, tenant_id="other-tenant")
    assert result.abstained is True
