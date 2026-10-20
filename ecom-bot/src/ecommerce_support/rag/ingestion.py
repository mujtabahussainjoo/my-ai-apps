"""Versioned document ingestion with content-hash dedupe and status tracking (TASK-017, DATA-006).

This module orchestrates the persistence side of ingestion: it is *transaction-scoped* and never
commits. The caller owns the transaction (``db.session.session_scope``), which lets an upper layer
roll back a failed ingest and then record the failure in a fresh transaction without losing it.

Contract:
- :func:`ingest_document` re-ingests only when the normalized content actually changed; an
  unchanged, already-indexed source is a no-op (``deduplicated=True``) and creates no new version.
- A changed source becomes a new version; the previously indexed version is marked ``superseded``.
- :func:`mark_ingestion_failed` persists a ``failed`` version with the error text for triage.

Embeddings are added in TASK-018; this task stores chunks with a null vector.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.core.config import get_settings
from ecommerce_support.core.ids import new_id
from ecommerce_support.db.repositories.document import DocumentRepository
from ecommerce_support.rag.chunking import chunk_text
from ecommerce_support.rag.embeddings.base import EmbeddingProvider
from ecommerce_support.rag.hashing import content_hash
from ecommerce_support.rag.loaders import LoadedDocument
from ecommerce_support.rag.store import PgVectorStore
from ecommerce_support.schemas.common import Schema
from ecommerce_support.schemas.documents import DocumentChunk, PolicyDocument
from ecommerce_support.schemas.enums import DocumentStatus

_MAX_TITLE = 300
_MAX_ERROR = 2000


class IngestionResult(Schema):
    """Outcome of ingesting a single source: the stored document version and dedupe flag."""

    document: PolicyDocument
    deduplicated: bool
    chunk_count: int


async def ingest_document(
    session: AsyncSession,
    loaded: LoadedDocument,
    *,
    tenant_id: str = "default",
    title: str | None = None,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
    default_section_title: str | None = None,
    embedder: EmbeddingProvider | None = None,
) -> IngestionResult:
    """Chunk and persist ``loaded`` as a new version, or return the existing version unchanged.

    When ``embedder`` is provided (TASK-018), chunk vectors are computed and stored in pgvector;
    otherwise chunks are stored with null vectors. Embedding dimension is validated both by the
    provider and by :class:`~ecommerce_support.rag.store.PgVectorStore`.

    Raises whatever :func:`ecommerce_support.rag.chunking.chunk_text` raises for invalid chunk
    configuration; the caller should roll back and then call :func:`mark_ingestion_failed`.
    """
    if chunk_size is None or chunk_overlap is None:
        rag = get_settings().rag
        chunk_size = rag.chunk_size if chunk_size is None else chunk_size
        chunk_overlap = rag.chunk_overlap if chunk_overlap is None else chunk_overlap

    repo = DocumentRepository(session)
    digest = content_hash(loaded.text)
    latest = await repo.get_latest_by_source(tenant_id=tenant_id, source=loaded.source)

    if (
        latest is not None
        and latest.content_hash == digest
        and latest.status is DocumentStatus.INDEXED
    ):
        return IngestionResult(document=latest, deduplicated=True, chunk_count=latest.chunk_count)

    version = latest.version + 1 if latest is not None else 1
    document = await repo.create(
        title=title or derive_title(loaded),
        source=loaded.source,
        version=version,
        content_hash=digest,
        status=DocumentStatus.PROCESSING,
        tenant_id=tenant_id,
    )
    if latest is not None and latest.status is not DocumentStatus.SUPERSEDED:
        await repo.supersede(latest.id)

    drafts = chunk_text(
        loaded.text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        default_section_title=default_section_title,
    )
    chunks = [
        DocumentChunk(
            id=new_id("chk"),
            document_id=document.id,
            version=version,
            chunk_index=draft.index,
            content=draft.content,
            content_hash=draft.content_hash,
            section_title=draft.section_title,
            token_count=draft.token_count,
        )
        for draft in drafts
    ]
    if embedder is not None:
        embeddings = await embedder.embed([chunk.content for chunk in chunks])
        await PgVectorStore(session).replace_document_chunks(document.id, chunks, embeddings)
    else:
        await repo.replace_chunks(document.id, chunks)
    updated = await repo.update_status(
        document.id, status=DocumentStatus.INDEXED, chunk_count=len(chunks)
    )
    if updated is None:  # pragma: no cover - row was just created in this transaction
        msg = f"document {document.id} disappeared during ingestion"
        raise LookupError(msg)
    return IngestionResult(document=updated, deduplicated=False, chunk_count=len(chunks))


async def mark_ingestion_failed(
    session: AsyncSession,
    *,
    tenant_id: str = "default",
    source: str,
    title: str | None = None,
    error: object,
) -> PolicyDocument:
    """Persist a ``failed`` version (newest version number) carrying the error text.

    Call this in a *fresh* transaction after rolling back the failed ingest, so the abandoned
    ``processing`` row is gone and only the recorded failure remains.
    """
    repo = DocumentRepository(session)
    latest = await repo.get_latest_by_source(tenant_id=tenant_id, source=source)
    version = latest.version + 1 if latest is not None else 1
    document = await repo.create(
        title=title or derive_title_from_source(source),
        source=source,
        version=version,
        content_hash=content_hash(f"{source}:{version}:error"),
        status=DocumentStatus.FAILED,
        tenant_id=tenant_id,
    )
    updated = await repo.update_status(
        document.id,
        status=DocumentStatus.FAILED,
        chunk_count=0,
        error_message=_format_error(error),
    )
    return updated if updated is not None else document


def derive_title(loaded: LoadedDocument) -> str:
    """Derive a human-readable title from the filename, then the source path."""
    if loaded.filename:
        stem = Path(loaded.filename).stem.strip()
        if stem:
            return _truncate_title(stem)
    return derive_title_from_source(loaded.source)


def derive_title_from_source(source: str) -> str:
    """Derive a document title from a source path/URI."""
    name = Path(source).stem.strip()
    return (name or source.strip() or "document")[:_MAX_TITLE]


def _format_error(error: object) -> str:
    text = f"{type(error).__name__}: {error}" if isinstance(error, BaseException) else str(error)
    return _truncate(text.strip() or "unknown error", _MAX_ERROR)


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def _truncate_title(title: str) -> str:
    return title[:_MAX_TITLE]
