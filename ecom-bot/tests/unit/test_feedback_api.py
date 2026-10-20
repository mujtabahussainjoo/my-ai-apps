"""API tests for feedback endpoints (TASK-030) via dependency override (no live DB)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ecommerce_support.api.dependencies import get_conversation_service, get_feedback_service
from ecommerce_support.core.exceptions import NotFoundError
from ecommerce_support.main import create_app
from ecommerce_support.schemas import Feedback, FeedbackReport, FeedbackRequest


class StubFeedbackService:
    def __init__(self) -> None:
        self.requests: list[FeedbackRequest] = []
        self.not_found = False

    async def create(self, request: FeedbackRequest) -> Feedback:
        if self.not_found:
            raise NotFoundError("Conversation not found.")
        self.requests.append(request)
        return Feedback(
            id="fb_1",
            conversation_id=request.conversation_id,
            rating=request.rating,
            comment=request.comment,
            resolution_outcome=request.resolution_outcome,
            created_at=datetime(2026, 10, 2, tzinfo=UTC),
        )

    async def report(self) -> FeedbackReport:
        return FeedbackReport(total=3, average_rating=4.5, by_rating={5: 2, 4: 1})

    async def list_for_conversation(self, conversation_id: str) -> list[Feedback]:
        return [
            Feedback(
                id="fb_1",
                conversation_id=conversation_id,
                rating=5,
                created_at=datetime(2026, 10, 2, tzinfo=UTC),
            )
        ]


@pytest.fixture
def stub_service() -> StubFeedbackService:
    return StubFeedbackService()


@pytest.fixture
def api_app(stub_service: StubFeedbackService, settings, conversation_access) -> FastAPI:
    app = create_app(settings)
    app.dependency_overrides[get_feedback_service] = lambda: stub_service
    app.dependency_overrides[get_conversation_service] = lambda: conversation_access
    return app


@pytest.fixture
async def api_client(api_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=api_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_submit_feedback_created(api_client: AsyncClient, stub_service) -> None:
    response = await api_client.post(
        "/api/v1/feedback",
        json={"conversation_id": "conv-1", "rating": 5, "comment": "great"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["conversation_id"] == "conv-1"
    assert body["rating"] == 5
    assert len(stub_service.requests) == 1


async def test_submit_feedback_rejects_invalid_rating(api_client: AsyncClient) -> None:
    response = await api_client.post(
        "/api/v1/feedback", json={"conversation_id": "conv-1", "rating": 9}
    )
    assert response.status_code == 422


async def test_submit_feedback_missing_conversation_returns_404(
    api_client: AsyncClient, stub_service: StubFeedbackService
) -> None:
    stub_service.not_found = True
    response = await api_client.post(
        "/api/v1/feedback", json={"conversation_id": "missing", "rating": 5}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_report_requires_admin_scope(api_client: AsyncClient) -> None:
    assert (await api_client.get("/api/v1/feedback/report")).status_code == 401


async def test_report_endpoint(api_client: AsyncClient, auth_headers) -> None:
    response = await api_client.get(
        "/api/v1/feedback/report", headers=auth_headers("admin", ["support:admin"])
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["average_rating"] == 4.5
    assert body["by_rating"] == {"5": 2, "4": 1}


async def test_report_rejects_insufficient_scope(api_client: AsyncClient, auth_headers) -> None:
    response = await api_client.get("/api/v1/feedback/report", headers=auth_headers("u-1"))
    assert response.status_code == 403


async def test_list_feedback_by_conversation(api_client: AsyncClient, conversation_access) -> None:
    response = await api_client.get("/api/v1/feedback", params={"conversation_id": "conv-1"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["conversation_id"] == "conv-1"
    assert conversation_access.calls == [("conv-1", None)]


async def test_list_feedback_requires_conversation_id(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/feedback")
    assert response.status_code == 422
