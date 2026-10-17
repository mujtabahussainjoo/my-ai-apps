"""Policy document and chunk repository (versioning, dedupe, embeddings; DATA-006)."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select

from ecommerce_support.core.ids import new_id
from ecommerce_support.db.models import DocumentChunk as ChunkRow
from ecommerce_support.db.models import PolicyDocument as DocumentRow
from ecommerce_support.db.repositories.base import BaseRepository
from ecommerce_support.schemas import DocumentChunk, PolicyDocument
from ecommerce_support.schemas.enums import DocumentStatus


def _to_document(row: DocumentRow) -> PolicyDocument:
    return PolicyDocument(
        id=row.id,
        title=row.title,
        source=row.source,
        version=row.version,
        content_hash=row.content_hash,
        status=row.status,
        chunk_count=row.chunk_count,
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
