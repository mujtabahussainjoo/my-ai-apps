"""Document ingestion/read use-cases for the API (FR-029, FR-007).

Thin framework-free wrapper over the RAG ingestion pipeline: it builds a validated
:class:`LoadedDocument` from an inline request, delegates chunk/embed/persist to
:func:`~ecommerce_support.rag.ingestion.ingest_document`, and exposes versioned reads.
The caller (HTTP dependency) owns the transaction/commit boundary.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ecommerce_support.core.exceptions import NotFoundError, UnsupportedDocumentTypeError
from ecommerce_support.db.repositories import DocumentRepository
from ecommerce_support.rag.embeddings.base import EmbeddingProvider
from ecommerce_support.rag.ingestion import IngestionResult, ingest_document
from ecommerce_support.rag.loaders import LoadedDocument, detect_document_type
from ecommerce_support.schemas import DocumentIngestRequest, Page, PageParams, PolicyDocument


class DocumentService:
    """Ingests policy documents and serves versioned reads."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        tenant_id: str = "default",
        embedder: EmbeddingProvider | None = None,
    ) -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._embedder = embedder
        self._documents = DocumentRepository(session)

    async def ingest(self, request: DocumentIngestRequest) -> IngestionResult:
        """Validate, chunk, embed, and persist a document version (idempotent by content)."""
        try:
            document_type = detect_document_type(
                media_type=request.media_type, filename=request.source
            )
        except UnsupportedDocumentTypeError:
            document_type = detect_document_type(media_type=request.media_type, filename=None)
        loaded = LoadedDocument(
            source=request.source,
            filename=request.source,
            media_type=request.media_type,
            document_type=document_type,
            byte_size=len(request.content.encode("utf-8")),
            text=request.content,
        )
        return await ingest_document(
            self._session,
            loaded,
            tenant_id=self._tenant_id,
            title=request.title,
            embedder=self._embedder,
        )

    async def get(self, document_id: str) -> PolicyDocument:
        document = await self._documents.get(document_id)
        if document is None:
            raise NotFoundError("Document not found.", details={"document_id": document_id})
        return document

    async def list(self, *, params: PageParams | None = None) -> Page[PolicyDocument]:
        params = params or PageParams()
        items, total = await self._documents.list_documents(
            tenant_id=self._tenant_id, limit=params.limit, offset=params.offset
        )
        return Page[PolicyDocument](
            items=items, total=total, limit=params.limit, offset=params.offset
        )


__all__ = ["DocumentService"]
