"""Policy-document endpoints (FR-029): ingest and read versioned knowledge sources.

Ingestion is versioned and content-deduplicated by :class:`DocumentService`; reads expose the
stored document metadata (chunks/citations are surfaced through the RAG answer flow, not here).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status

from ecommerce_support.api.dependencies import get_document_service
from ecommerce_support.rag.ingestion import IngestionResult
from ecommerce_support.schemas import DocumentIngestRequest, Page, PageParams, PolicyDocument
from ecommerce_support.services.documents import DocumentService

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])


@router.post(
    "",
    response_model=IngestionResult,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a policy document",
    description="Chunk, embed, and persist a versioned document; unchanged content is a no-op.",
)
async def ingest_document(
    request: DocumentIngestRequest,
    service: DocumentService = Depends(get_document_service),
) -> IngestionResult:
    return await service.ingest(request)


@router.get(
    "",
    response_model=Page[PolicyDocument],
    summary="List documents",
    description="List policy documents for the tenant, newest first (FR-008/FR-029).",
)
async def list_documents(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: DocumentService = Depends(get_document_service),
) -> Page[PolicyDocument]:
    return await service.list(params=PageParams(limit=limit, offset=offset))


@router.get(
    "/{document_id}",
    response_model=PolicyDocument,
    summary="Get a document",
    description="Return a stored document version by id (FR-029).",
)
async def get_document(
    document_id: str,
    service: DocumentService = Depends(get_document_service),
) -> PolicyDocument:
    return await service.get(document_id)
