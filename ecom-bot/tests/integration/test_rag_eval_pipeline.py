"""Integration test: end-to-end baseline RAG evaluation over a live DB (TASK-021).

Ingests the checked-in corpus into a throwaway tenant, runs the versioned eval dataset through
the real retriever + grounded generator, and cleans up. Runs inside a rolled-back transaction;
skipped automatically when the database is unreachable.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.db.repositories import DocumentRepository
from ecommerce_support.evaluation.rag import RagEvaluator, load_eval_dataset
from ecommerce_support.llm.providers.mock import MockLLMClient
from ecommerce_support.rag.embeddings.mock import MockEmbeddingProvider
from ecommerce_support.rag.generation import GroundedGenerator
from ecommerce_support.rag.ingestion import ingest_document
from ecommerce_support.rag.loaders import LoadedDocument, load_document
from ecommerce_support.rag.rerank import LexicalReranker
from ecommerce_support.rag.retrieval import Retriever
from ecommerce_support.rag.store import PgVectorStore

pytestmark = pytest.mark.integration

_CORPUS = Path("evals/corpus")
_DATASET = Path("evals/rag_dataset.yaml")


def _title_for(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").title()


def _load_corpus() -> list[tuple[str, LoadedDocument]]:
    entries: list[tuple[str, LoadedDocument]] = []
    for path in sorted(p for p in _CORPUS.glob("*") if p.is_file()):
        loaded = load_document(source=str(path), data=path.read_bytes(), filename=path.name)
        entries.append((_title_for(path), loaded))
    return entries


async def _ingest_corpus(session: AsyncSession, tenant: str) -> int:
    embedder = MockEmbeddingProvider()
    count = 0
    for title, loaded in _load_corpus():
        await ingest_document(
            session,
            loaded,
            tenant_id=tenant,
            title=title,
            embedder=embedder,
            chunk_size=1000,
            chunk_overlap=0,
        )
        count += 1
    return count


async def _retriever(session: AsyncSession) -> Retriever:
    return Retriever(
        embedder=MockEmbeddingProvider(),
        store=PgVectorStore(session),
        top_k=20,
        distance_threshold=None,
        rerank_enabled=True,
        rerank_top_n=50,
        reranker=LexicalReranker(),
    )


async def test_eval_pipeline_reports_metrics(session: AsyncSession) -> None:
    tenant = f"eval-{uuid4().hex[:8]}"
    corpus_size = await _ingest_corpus(session, tenant)
    assert corpus_size >= 3

    dataset = load_eval_dataset(_DATASET)
    generator = GroundedGenerator(MockLLMClient())
    evaluator = RagEvaluator(
        await _retriever(session), generator, top_k=20, distance_threshold=None, tenant_id=tenant
    )
    report = await evaluator.evaluate(dataset)

    assert report.case_count == len(dataset.cases)
    assert 0.0 <= report.mean_recall <= 1.0
    assert report.mean_recall == pytest.approx(1.0)
    assert report.mean_groundedness > 0.0

    answerable = [s for s in report.scores if s.case_id != "gift-wrapping"]
    assert all(s.recall == 1.0 for s in answerable)
    assert all(s.groundedness == 1.0 for s in answerable)
    assert all(s.citation_count >= 1 for s in answerable)


async def test_delete_by_tenant_removes_documents(session: AsyncSession) -> None:
    tenant = f"eval-{uuid4().hex[:8]}"
    await _ingest_corpus(session, tenant)
    repo = DocumentRepository(session)
    _documents, total = await repo.list_documents(tenant_id=tenant, limit=50)
    assert total == 3

    removed = await repo.delete_by_tenant(tenant)
    assert removed == 3
    _, remaining = await repo.list_documents(tenant_id=tenant, limit=50)
    assert remaining == 0
