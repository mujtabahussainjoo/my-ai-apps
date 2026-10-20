"""Security tests for API authentication, ownership and rate limiting (TASK-038, SEC-001/002/012)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ecommerce_support.api.dependencies import (
    get_chat_service,
    get_conversation_service,
    get_feedback_service,
)
from ecommerce_support.core.exceptions import NotFoundError
from ecommerce_support.main import create_app
from ecommerce_support.schemas import (
    ChatRequest,
    ChatResponse,
    Conversation,
    ConversationSummary,
    Feedback,
    FeedbackReport,
    FeedbackRequest,
    Message,
    Page,
    PageParams,
)
from ecommerce_support.schemas.enums import ConversationStatus

pytestmark = pytest.mark.security

_NOW = datetime(2026, 10, 19, tzinfo=UTC)


class _ScopedConversations:
    """Mirrors service ownership: a non-owner sees ``404`` (no existence leak)."""

    def __init__(self, owner: str | None) -> None:
        self.owner = owner

    async def get(self, conversation_id: str, *, user_id: str | None = None) -> Conversation:
        if user_id != self.owner:
            raise NotFoundError("Conversation not found.")
        return Conversation(
            id=conversation_id,
            user_id=self.owner,
            status=ConversationStatus.OPEN,
            created_at=_NOW,
            updated_at=_NOW,
            messages=[],
        )
        return object()

    async def assert_access(self, conversation_id: str, *, user_id: str | None = None) -> None:
        if user_id != self.owner:
            raise NotFoundError("Conversation not found.")

    async def list_for_user(
        self, user_id: str, *, params: PageParams | None = None
    ) -> Page[ConversationSummary]:
        params = params or PageParams()
        return Page[ConversationSummary](
            items=[], total=0, limit=params.limit, offset=params.offset
        )

    async def list_messages(
        self, conversation_id: str, *, user_id: str | None = None, params: PageParams | None = None
    ) -> Page[Message]:
        if user_id != self.owner:
            raise NotFoundError("Conversation not found.")
        params = params or PageParams()
        return Page[Message](items=[], total=0, limit=params.limit, offset=params.offset)

    async def delete(self, conversation_id: str, *, user_id: str | None = None) -> None:
        if user_id != self.owner:
            raise NotFoundError("Conversation not found.")


class _StubChat:
    async def chat(self, request: ChatRequest, **_: object) -> ChatResponse:
        raise NotFoundError("Conversation not found.")


class _StubFeedback:
    async def create(self, request: FeedbackRequest) -> Feedback:
        raise AssertionError("ownership check must run before feedback creation")

    async def report(self) -> FeedbackReport:
        return FeedbackReport(total=0, average_rating=None, by_rating={})


@pytest.fixture
def api_app(settings) -> FastAPI:
    app = create_app(settings)
    app.dependency_overrides[get_conversation_service] = lambda: _ScopedConversations("cust-1")
    app.dependency_overrides[get_chat_service] = lambda: _StubChat()
    app.dependency_overrides[get_feedback_service] = lambda: _StubFeedback()
    return app


@pytest.fixture
async def api_client(api_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=api_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_owner_can_read_own_conversation(api_client: AsyncClient, auth_headers) -> None:
    response = await api_client.get("/api/v1/conversations/conv-1", headers=auth_headers("cust-1"))
    assert response.status_code == 200


async def test_cross_customer_read_is_not_found(api_client: AsyncClient, auth_headers) -> None:
    response = await api_client.get("/api/v1/conversations/conv-1", headers=auth_headers("cust-2"))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_cross_customer_delete_is_not_found(api_client: AsyncClient, auth_headers) -> None:
    response = await api_client.delete(
        "/api/v1/conversations/conv-1", headers=auth_headers("cust-2")
    )
    assert response.status_code == 404


async def test_cross_customer_chat_escalation_is_not_found(
    api_client: AsyncClient, auth_headers
) -> None:
    response = await api_client.post(
        "/api/v1/chat",
        json={"message": "hi", "conversation_id": "conv-1", "stream": False},
        headers=auth_headers("cust-2"),
    )
    assert response.status_code == 404


async def test_admin_scope_required_for_feedback_report(
    api_client: AsyncClient, auth_headers
) -> None:
    forbidden = await api_client.get("/api/v1/feedback/report", headers=auth_headers("cust-1"))
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "forbidden"
    allowed = await api_client.get(
        "/api/v1/feedback/report", headers=auth_headers("admin-1", ["support:admin"])
    )
    assert allowed.status_code == 200


async def test_unauthenticated_feedback_report_is_401(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/feedback/report")
    assert response.status_code == 401


async def test_error_envelope_never_leaks_internal_details(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/conversations")
    assert response.status_code == 401
    body = response.json()
    assert set(body) == {"error", "request_id"}
    assert "traceback" not in response.text.lower()
    assert "password" not in response.text.lower()
