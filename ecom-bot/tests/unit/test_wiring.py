"""Composition-root tests: AppWiring builds services without network/credentials (TASK-035)."""

from __future__ import annotations

import pytest

from ecommerce_support.api.wiring import AppWiring
from ecommerce_support.core.config import Settings
from ecommerce_support.services import ChatService, TicketService
from ecommerce_support.services.conversations import ConversationService
from ecommerce_support.services.documents import DocumentService


class _DummySession:
    """Sentinel session: wiring must not touch the database while constructing services."""

    async def commit(self) -> None:
        return None


@pytest.fixture
def wiring(settings: Settings) -> AppWiring:
    return AppWiring(settings)


def test_wiring_builds_chat_service(wiring: AppWiring) -> None:
    service = wiring.build_chat_service(_DummySession())  # type: ignore[arg-type]
    assert isinstance(service, ChatService)


def test_wiring_builds_supporting_services(wiring: AppWiring) -> None:
    assert isinstance(wiring.build_ticket_service(_DummySession()), TicketService)  # type: ignore[arg-type]
    assert isinstance(  # type: ignore[arg-type]
        wiring.build_conversation_service(_DummySession()), ConversationService
    )
    assert isinstance(wiring.build_document_service(_DummySession()), DocumentService)  # type: ignore[arg-type]


def test_wiring_caches_stateless_clients(wiring: AppWiring) -> None:
    assert wiring.embedder is wiring.embedder
    assert wiring.ticketing is wiring.ticketing
    assert wiring.generation_client is wiring.generation_client
