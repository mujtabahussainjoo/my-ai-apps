"""Integration test: ingest → retrieve → grounded answer with real citations (TASK-020).

Skipped automatically when the compose database is unreachable; runs in a rolled-back txn.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.core.config import RagConfig
from ecommerce_support.llm.providers.mock import MockLLMClient
from ecommerce_support.rag.embeddings.mock import MockEmbeddingProvider
from ecommerce_support.rag.generation import GroundedGenerator
from ecommerce_support.rag.ingestion import ingest_document
from ecommerce_support.rag.loaders import load_document
from ecommerce_support.rag.retrieval import Retriever

pytestmark = pytest.mark.integration

_REFUND_TEXT = "Refund window is thirty days from delivery."


async def _ingest(session: AsyncSession, text: str = _REFUND_TEXT) -> str:
    source = f"policy-{uuid4()}.md"
    loaded = load_document(source=source, data=text.encode(), filename="policy.md")
    result = await ingest_document(
        session, loaded, embedder=MockEmbeddingProvider(), chunk_size=1000, chunk_overlap=0
    )
    return result.document.id


async def test_grounded_answer_cites_ingested_chunk(session: AsyncSession) -> None:
    document_id = await _ingest(session)
    retriever = Retriever.from_session(session, MockEmbeddingProvider(), RagConfig())
    retrieval = await retriever.retrieve(_REFUND_TEXT)
    assert retrieval.abstained is False

    client = MockLLMClient(completions=["Refunds are accepted within thirty days [1]."])
    answer = await GroundedGenerator(client).answer("what is the refund window?", retrieval)

    assert answer.abstained is False
    assert answer.answer.startswith("Refunds are accepted")
    assert answer.citations
    citation = answer.citations[0]
    assert citation.document_id == document_id
    assert citation.chunk_id == retrieval.hits[0].chunk.id


async def test_abstains_end_to_end_for_unrelated_question(session: AsyncSession) -> None:
    await _ingest(session)
    retriever = Retriever.from_session(session, MockEmbeddingProvider(), RagConfig())
    retrieval = await retriever.retrieve("how do I pay with cryptocurrency")
    client = MockLLMClient()
    answer = await GroundedGenerator(client).answer("how do I pay with cryptocurrency", retrieval)
    assert answer.abstained is True
    assert answer.citations == []
    assert client.requests == []
