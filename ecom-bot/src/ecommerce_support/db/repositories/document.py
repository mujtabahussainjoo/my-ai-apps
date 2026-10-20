"""Policy document and chunk repository (versioning, dedupe, embeddings; DATA-006)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.sql.elements import ColumnElement

from ecommerce_support.core.exceptions import ConfigurationError, ValidationError
from ecommerce_support.core.ids import new_id
from ecommerce_support.db.models import DocumentChunk as ChunkRow
from ecommerce_support.db.models import PolicyDocument as DocumentRow
from ecommerce_support.db.repositories.base import BaseRepository
from ecommerce_support.schemas import ChunkSearchHit, DocumentChunk, PolicyDocument
from ecommerce_support.schemas.enums import DocumentStatus

_DISTANCE_METHODS = {
    "cosine": "cosine_distance",
    "l2": "l2_distance",
    "ip": "max_inner_product",
}

_FILTER_COLUMNS: dict[str, Any] = {
    "document_id": ChunkRow.document_id,
    "version": ChunkRow.version,
    "section_title": ChunkRow.section_title,
    "source": DocumentRow.source,
    "title": DocumentRow.title,
}


def _to_document(row: DocumentRow) -> PolicyDocument:
    return PolicyDocument(
        id=row.id,
        title=row.title,
        source=row.source,
        version=row.version,
        content_hash=row.content_hash,
        status=row.status,
        chunk_count=row.chunk_count,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _to_chunk(row: ChunkRow) -> DocumentChunk:
    return DocumentChunk(
        id=row.id,
        document_id=row.document_id,
        version=row.version,
        chunk_index=row.chunk_index,
        content=row.content,
        content_hash=row.content_hash,
        section_title=row.section_title,
        token_count=row.token_count,
    )


class DocumentRepository(BaseRepository):
    """Persistence for versioned policy documents and their chunks."""

    async def create(
        self,
        *,
        title: str,
        source: str,
        version: int,
        content_hash: str,
        status: DocumentStatus = DocumentStatus.PENDING,
        tenant_id: str = "default",
        document_id: str | None = None,
    ) -> PolicyDocument:
        row = DocumentRow(
            id=document_id or new_id("doc"),
            tenant_id=tenant_id,
            title=title,
            source=source,
            version=version,
            content_hash=content_hash,
            status=status,
        )
        self.session.add(row)
        await self.session.flush()
        return _to_document(row)

    async def get(self, document_id: str) -> PolicyDocument | None:
        row = await self.session.get(DocumentRow, document_id)
        return _to_document(row) if row is not None else None

    async def get_by_source_version(
        self, *, tenant_id: str, source: str, version: int
    ) -> PolicyDocument | None:
        row = await self.session.scalar(
            select(DocumentRow).where(
                DocumentRow.tenant_id == tenant_id,
                DocumentRow.source == source,
                DocumentRow.version == version,
            )
        )
        return _to_document(row) if row is not None else None

    async def get_latest_by_source(self, *, tenant_id: str, source: str) -> PolicyDocument | None:
        """Return the most recent version for a source, or None if never ingested."""
        row = await self.session.scalar(
            select(DocumentRow)
            .where(DocumentRow.tenant_id == tenant_id, DocumentRow.source == source)
            .order_by(DocumentRow.version.desc())
            .limit(1)
        )
        return _to_document(row) if row is not None else None

    async def update_status(
        self,
        document_id: str,
        *,
        status: DocumentStatus,
        chunk_count: int | None = None,
        error_message: str | None = None,
    ) -> PolicyDocument | None:
        """Update ingestion status; ``chunk_count``/``error_message`` are only set when given."""
        row = await self.session.get(DocumentRow, document_id)
        if row is None:
            return None
        row.status = status
        if chunk_count is not None:
            row.chunk_count = chunk_count
        row.error_message = error_message
        await self.session.flush()
        return _to_document(row)

    async def list_documents(
        self, *, tenant_id: str = "default", limit: int = 20, offset: int = 0
    ) -> tuple[list[PolicyDocument], int]:
        condition = DocumentRow.tenant_id == tenant_id
        total = await self.session.scalar(
            select(func.count()).select_from(DocumentRow).where(condition)
        )
        stmt = (
            select(DocumentRow)
            .where(condition)
            .order_by(DocumentRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = list((await self.session.scalars(stmt)).all())
        return [_to_document(row) for row in rows], int(total or 0)

    async def supersede(self, document_id: str) -> PolicyDocument | None:
        row = await self.session.get(DocumentRow, document_id)
        if row is None:
            return None
        row.status = DocumentStatus.SUPERSEDED
        await self.session.flush()
        return _to_document(row)

    async def replace_chunks(
        self,
        document_id: str,
        chunks: Sequence[DocumentChunk],
        embeddings: Sequence[list[float] | None] | None = None,
    ) -> int:
        """Delete existing chunks for a document and insert the new set."""
        await self.delete_chunks(document_id)
        embedding_list = list(embeddings) if embeddings is not None else [None] * len(chunks)
        if len(embedding_list) != len(chunks):
            msg = "embeddings and chunks must have the same length"
            raise ValueError(msg)
        for chunk, embedding in zip(chunks, embedding_list, strict=True):
            self.session.add(
                ChunkRow(
                    id=chunk.id or new_id("chk"),
                    document_id=document_id,
                    version=chunk.version,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    section_title=chunk.section_title,
                    token_count=chunk.token_count,
                    embedding=embedding,
                )
            )
        await self.session.flush()
        return len(chunks)

    async def list_chunks(self, document_id: str) -> list[DocumentChunk]:
        stmt = (
            select(ChunkRow)
            .where(ChunkRow.document_id == document_id)
            .order_by(ChunkRow.chunk_index.asc())
        )
        return [_to_chunk(row) for row in (await self.session.scalars(stmt)).all()]

    async def delete_chunks(self, document_id: str) -> int:
        rows = (
            await self.session.scalars(select(ChunkRow).where(ChunkRow.document_id == document_id))
        ).all()
        for row in rows:
            await self.session.delete(row)
        await self.session.flush()
        return len(rows)

    async def delete_by_tenant(self, tenant_id: str) -> int:
        """Delete every document and chunk for a tenant; returns the number of documents removed."""
        document_ids = list(
            (
                await self.session.scalars(
                    select(DocumentRow.id).where(DocumentRow.tenant_id == tenant_id)
                )
            ).all()
        )
        if not document_ids:
            return 0
        await self.session.execute(delete(ChunkRow).where(ChunkRow.document_id.in_(document_ids)))
        await self.session.execute(delete(DocumentRow).where(DocumentRow.id.in_(document_ids)))
        await self.session.flush()
        return len(document_ids)

    async def search_chunks(
        self,
        embedding: Sequence[float],
        *,
        tenant_id: str = "default",
        metric: str = "cosine",
        limit: int = 5,
        filters: Mapping[str, str] | None = None,
    ) -> list[ChunkSearchHit]:
        """Nearest-neighbor chunk search over indexed documents (FR-032).

        Only ``indexed`` documents of ``tenant_id`` are searched. ``filters`` may restrict by
        ``document_id``, ``version``, ``section_title``, ``source``, or ``title``; an unknown key
        fails loudly. Results are ordered by ascending distance (most similar first) and are not
        threshold-filtered here — the retrieval layer applies the abstention threshold.
        """
        distance = _distance_expression(ChunkRow.embedding, embedding, metric)
        conditions: list[ColumnElement[bool]] = [
            DocumentRow.tenant_id == tenant_id,
            DocumentRow.status == DocumentStatus.INDEXED,
            ChunkRow.embedding.is_not(None),
            *_filter_conditions(filters or {}),
        ]
        stmt = (
            select(ChunkRow, DocumentRow.title, distance.label("distance"))
            .join(DocumentRow, ChunkRow.document_id == DocumentRow.id)
            .where(*conditions)
            .order_by(distance.asc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            ChunkSearchHit(
                chunk=_to_chunk(chunk_row), document_title=title, distance=float(distance_value)
            )
            for chunk_row, title, distance_value in rows
        ]


def _distance_expression(column: Any, embedding: Sequence[float], metric: str) -> Any:
    method = _DISTANCE_METHODS.get(metric)
    if method is None:
        raise ConfigurationError(
            f"Unsupported distance metric {metric!r}.",
            details={"metric": metric, "supported": sorted(_DISTANCE_METHODS)},
        )
    return getattr(cast(Any, column), method)(list(embedding))


def _filter_conditions(filters: Mapping[str, str]) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = []
    for key, value in filters.items():
        column = _FILTER_COLUMNS.get(key)
        if column is None:
            raise ValidationError(
                "Unsupported retrieval filter.",
                details={"filter": key, "supported": sorted(_FILTER_COLUMNS)},
            )
        if key == "version":
            try:
                conditions.append(column == int(value))
            except ValueError as exc:
                raise ValidationError(
                    "The 'version' filter must be an integer.",
                    details={"value": value},
                ) from exc
        else:
            conditions.append(column == value)
    return conditions
