"""Integration tests for versioned ingestion with dedupe and error tracking (TASK-017).

Run against the compose database with migrations applied (`make db-up && make migrate`);
skipped automatically when it is unreachable. Each test runs inside a transaction that is
rolled back, so no rows persist.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.db.repositories import DocumentRepository
from ecommerce_support.rag.ingestion import ingest_document, mark_ingestion_failed
from ecommerce_support.rag.loaders import LoadedDocument, load_document
from ecommerce_support.schemas.enums import DocumentStatus

pytestmark = pytest.mark.integration

_MARKDOWN = """\
# Return Policy

Items may be returned within 30 days of delivery. The item must be unused and in its
original packaging.

## Refunds

Refunds are issued to the original payment method.
"""


def _source() -> str:
    return f"policy-{uuid4()}.md"


def _doc(source: str, data: bytes | None = None, *, filename: str = "policy.md") -> LoadedDocument:
    return load_document(
        source=source, data=data if data is not None else _MARKDOWN.encode(), filename=filename
    )


async def test_ingest_creates_indexed_version_with_chunks(session: AsyncSession) -> None:
    loaded = _doc(_source())
    result = await ingest_document(session, loaded)

    assert result.deduplicated is False
    assert result.document.status is DocumentStatus.INDEXED
    assert result.document.version == 1
    assert result.chunk_count == result.document.chunk_count
    assert result.chunk_count >= 1
    chunks = await DocumentRepository(session).list_chunks(result.document.id)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert any(chunk.section_title == "Return Policy" for chunk in chunks)


async def test_reingest_unchanged_content_is_deduplicated(session: AsyncSession) -> None:
    source = _source()
    first = await ingest_document(session, _doc(source))
    second = await ingest_document(session, _doc(source))

    assert second.deduplicated is True
    assert second.document.id == first.document.id
    assert second.document.version == 1


async def test_changed_content_creates_new_version_and_supersedes(session: AsyncSession) -> None:
    source = _source()
    repo = DocumentRepository(session)
    first = await ingest_document(session, _doc(source, b"Version one body."))
    second = await ingest_document(session, _doc(source, b"Version two body."))

    assert second.deduplicated is False
    assert second.document.version == 2
    superseded = await repo.get_by_source_version(tenant_id="default", source=source, version=1)
    assert superseded is not None
    assert superseded.status is DocumentStatus.SUPERSEDED
    latest = await repo.get_latest_by_source(tenant_id="default", source=source)
    assert latest is not None
    assert latest.version == 2
    assert first.document.content_hash != second.document.content_hash


async def test_ingested_chunks_store_null_embeddings(session: AsyncSession) -> None:
    """TASK-017 stores chunks; embeddings arrive in TASK-018."""
    result = await ingest_document(session, _doc(_source()))
    rows = await session.execute(
        text("SELECT embedding FROM document_chunks WHERE document_id = :doc"),
        {"doc": result.document.id},
    )
    embeddings = [row[0] for row in rows]
    assert embeddings
    assert all(value is None for value in embeddings)


async def test_mark_ingestion_failed_persists_error(session: AsyncSession) -> None:
    source = _source()
    document = await mark_ingestion_failed(
        session, source=source, error=ValueError("boom"), title="Broken policy"
    )

    assert document.status is DocumentStatus.FAILED
    assert document.chunk_count == 0
    assert document.error_message is not None
    assert "ValueError" in document.error_message
    assert "boom" in document.error_message
    stored = await DocumentRepository(session).get_latest_by_source(
        tenant_id="default", source=source
    )
    assert stored is not None
    assert stored.id == document.id


async def test_failed_version_follows_existing_version(session: AsyncSession) -> None:
    source = _source()
    await ingest_document(session, _doc(source, b"Good version."))
    document = await mark_ingestion_failed(session, source=source, error="parse error")
    assert document.version == 2
    assert document.status is DocumentStatus.FAILED
