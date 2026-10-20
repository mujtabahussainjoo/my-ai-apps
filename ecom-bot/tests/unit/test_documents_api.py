"""API tests for document endpoints (TASK-035) via dependency override (no live DB)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ecommerce_support.api.dependencies import get_document_service
from ecommerce_support.core.exceptions import NotFoundError
from ecommerce_support.main import create_app
from ecommerce_support.rag.ingestion import IngestionResult
from ecommerce_support.schemas import DocumentIngestRequest, Page, PageParams, PolicyDocument
from ecommerce_support.schemas.enums import DocumentStatus

_NOW = datetime(2026, 10, 12, tzinfo=UTC)


def _document(document_id: str = "doc_1") -> PolicyDocument:
    return PolicyDocument(
        id=document_id,
        title="Return policy",
        source="policies/returns.md",
        version=1,
        content_hash="abc123",
        status=DocumentStatus.INDEXED,
        chunk_count=3,
        created_at=_NOW,
    )


class StubDocumentService:
    def __init__(self) -> None:
        self.ingested: list[DocumentIngestRequest] = []
        self.not_found = False

    async def ingest(self, request: DocumentIngestRequest) -> IngestionResult:
        self.ingested.append(request)
        return IngestionResult(document=_document(), deduplicated=False, chunk_count=3)

    async def get(self, document_id: str) -> PolicyDocument:
        if self.not_found:
            raise NotFoundError("Document not found.")
        return _document(document_id)

    async def list(self, *, params: PageParams | None = None) -> Page[PolicyDocument]:
        params = params or PageParams()
        return Page[PolicyDocument](
            items=[_document()], total=1, limit=params.limit, offset=params.offset
        )


@pytest.fixture
def stub_service() -> StubDocumentService:
    return StubDocumentService()


@pytest.fixture
def api_app(stub_service: StubDocumentService, settings) -> FastAPI:
    app = create_app(settings)
    app.dependency_overrides[get_document_service] = lambda: stub_service
    return app


@pytest.fixture
async def api_client(api_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=api_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_ingest_document_created(api_client: AsyncClient, stub_service) -> None:
    response = await api_client.post(
        "/api/v1/documents",
        json={"source": "policies/returns.md", "content": "Returns accepted within 30 days."},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["chunk_count"] == 3
    assert body["document"]["status"] == "indexed"
    assert len(stub_service.ingested) == 1


async def test_ingest_rejects_empty_content(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/api/v1/documents", json={"source": "policies/returns.md", "content": ""}
    )
    assert response.status_code == 422


async def test_get_document(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/documents/doc_1")
    assert response.status_code == 200
    assert response.json()["source"] == "policies/returns.md"


async def test_get_missing_document_returns_404(
    api_client: AsyncClient, stub_service: StubDocumentService
) -> None:
    stub_service.not_found = True
    response = await api_client.get("/api/v1/documents/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_list_documents_paginated(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/documents", params={"limit": 2, "offset": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 2
    assert body["items"][0]["id"] == "doc_1"
