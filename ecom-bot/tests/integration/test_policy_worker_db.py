"""Integration test: policy worker over the real RAG pipeline (TASK-025).

Ingests a versioned policy document, then answers through the tool registry + grounded
generator. Skipped automatically when the compose database is unreachable.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.agents import PolicyWorker
from ecommerce_support.core.config import RagConfig
from ecommerce_support.llm.providers.mock import MockLLMClient
from ecommerce_support.rag.embeddings.mock import MockEmbeddingProvider
from ecommerce_support.rag.generation import GroundedGenerator
from ecommerce_support.rag.ingestion import ingest_document
from ecommerce_support.rag.loaders import load_document
from ecommerce_support.rag.retrieval import Retriever
from ecommerce_support.schemas.agents import ToolContext
from ecommerce_support.schemas.enums import AgentName
from ecommerce_support.tools import create_policy_registry

pytestmark = pytest.mark.integration

_POLICY_TEXT = "Refund window is thirty days from delivery."


async def _ingest(session: AsyncSession) -> None:
    loaded = load_document(
        source=f"policy-{uuid4()}.md", data=_POLICY_TEXT.encode(), filename="policy.md"
    )
    await ingest_document(
        session, loaded, embedder=MockEmbeddingProvider(), chunk_size=1000, chunk_overlap=0
    )


async def test_policy_worker_answers_with_citation(session: AsyncSession) -> None:
    await _ingest(session)
    retriever = Retriever.from_session(session, MockEmbeddingProvider(), RagConfig())
    worker = PolicyWorker(
        create_policy_registry(retriever),
        GroundedGenerator(MockLLMClient(completions=["Refunds allowed for 30 days [1]."])),
    )

    response = await worker.answer(
        _POLICY_TEXT,
        context=ToolContext(agent=AgentName.POLICY, conversation_id="conv-1"),
    )

    assert response.abstained is False
    assert len(response.citations) == 1
    assert response.citations[0].document_title


async def test_policy_worker_abstains_for_unknown(session: AsyncSession) -> None:
    await _ingest(session)
    retriever = Retriever.from_session(session, MockEmbeddingProvider(), RagConfig())
    client = MockLLMClient()
    worker = PolicyWorker(create_policy_registry(retriever), GroundedGenerator(client))

    response = await worker.answer(
        "How do I pay with cryptocurrency?",
        context=ToolContext(agent=AgentName.POLICY, conversation_id="conv-1"),
    )

    assert response.abstained is True
    assert response.citations == []
    assert client.requests == []
