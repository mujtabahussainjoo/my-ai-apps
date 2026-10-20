"""API tests for ticket endpoints (TASK-035) via dependency override (no live DB)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ecommerce_support.api.dependencies import get_conversation_service, get_ticket_service
from ecommerce_support.main import create_app
from ecommerce_support.schemas import Ticket
from ecommerce_support.schemas.enums import Priority, TicketProvider, TicketStatus

_NOW = datetime(2026, 10, 12, tzinfo=UTC)


def _ticket(
    ticket_id: str = "tkt_1",
    *,
    conversation_id: str = "conv_1",
    status: TicketStatus = TicketStatus.CREATED,
) -> Ticket:
    return Ticket(
        id=ticket_id,
        conversation_id=conversation_id,
        provider=TicketProvider.MOCK,
        status=status,
        summary="Order never arrived",
        priority=Priority.MEDIUM,
        external_id="mock_1",
        url="https://mock.tickets.local/mock_1",
        created_at=_NOW,
    )


class StubTicketService:
    def __init__(self) -> None:
        self.refreshed: list[str] = []
        self.not_found = False

    async def list_for_conversation(self, conversation_id: str) -> list[Ticket]:
        return [_ticket(conversation_id=conversation_id)]

    async def get(self, ticket_id: str) -> Ticket | None:
        return None if self.not_found else _ticket(ticket_id)

    async def refresh_status(self, ticket_id: str) -> Ticket | None:
        self.refreshed.append(ticket_id)
        return None if self.not_found else _ticket(ticket_id, status=TicketStatus.IN_PROGRESS)


@pytest.fixture
def stub_service() -> StubTicketService:
    return StubTicketService()


@pytest.fixture
def api_app(stub_service: StubTicketService, settings, conversation_access) -> FastAPI:
    app = create_app(settings)
    app.dependency_overrides[get_ticket_service] = lambda: stub_service
    app.dependency_overrides[get_conversation_service] = lambda: conversation_access
    return app


@pytest.fixture
async def api_client(api_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=api_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_list_tickets_requires_conversation_id(api_client: AsyncClient) -> None:
    assert (await api_client.get("/api/v1/tickets")).status_code == 422


async def test_list_tickets_for_conversation(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/tickets", params={"conversation_id": "conv_1"})
    assert response.status_code == 200
    body = response.json()
    assert body[0]["id"] == "tkt_1"
    assert body[0]["conversation_id"] == "conv_1"
    assert body[0]["status"] == "created"


async def test_get_ticket(api_client: AsyncClient) -> None:
    response = await api_client.get("/api/v1/tickets/tkt_1")
    assert response.status_code == 200
    assert response.json()["provider"] == "mock"


async def test_get_missing_ticket_returns_404(
    api_client: AsyncClient, stub_service: StubTicketService
) -> None:
    stub_service.not_found = True
    response = await api_client.get("/api/v1/tickets/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_refresh_ticket(api_client: AsyncClient, stub_service) -> None:
    response = await api_client.post("/api/v1/tickets/tkt_1/refresh")
    assert response.status_code == 200
    assert stub_service.refreshed == ["tkt_1"]
    assert response.json()["status"] == "in_progress"
