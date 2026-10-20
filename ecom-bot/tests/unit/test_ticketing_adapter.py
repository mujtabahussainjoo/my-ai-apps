"""Unit tests for the ticketing adapter interface + mock integration (TASK-031)."""

from __future__ import annotations

import pytest

from ecommerce_support.core.config import TicketingProvider
from ecommerce_support.core.exceptions import ConfigurationError, TicketCreationError
from ecommerce_support.integrations import (
    MockTicketingAdapter,
    TicketingAdapter,
    create_ticketing_adapter,
)
from ecommerce_support.schemas import ExternalTicket, TicketRequest
from ecommerce_support.schemas.enums import TicketProvider, TicketStatus


def _request(**overrides: object) -> TicketRequest:
    data: dict[str, object] = {"conversation_id": "conv-1", "summary": "Order never arrived"}
    data.update(overrides)
    return TicketRequest(**data)


def test_mock_is_a_ticketing_adapter() -> None:
    assert isinstance(MockTicketingAdapter(), TicketingAdapter)
    assert MockTicketingAdapter.provider is TicketProvider.MOCK


async def test_create_returns_confirmed_ticket() -> None:
    adapter = MockTicketingAdapter()
    ticket = await adapter.create_ticket(_request())
    assert isinstance(ticket, ExternalTicket)
    assert ticket.provider is TicketProvider.MOCK
    assert ticket.status is TicketStatus.CREATED
    assert ticket.external_id.startswith("mock_")
    assert ticket.url and ticket.external_id in ticket.url
    assert len(adapter.calls) == 1


async def test_get_status_round_trip() -> None:
    adapter = MockTicketingAdapter()
    created = await adapter.create_ticket(_request())
    fetched = await adapter.get_status(created.external_id)
    assert fetched == created
    assert await adapter.get_status("mock_missing") is None


async def test_fail_next_then_succeeds() -> None:
    adapter = MockTicketingAdapter(fail_next=1)
    with pytest.raises(TicketCreationError) as excinfo:
        await adapter.create_ticket(_request())
    assert excinfo.value.code == "ticket_creation_failed"
    assert excinfo.value.retryable is True
    ticket = await adapter.create_ticket(_request())
    assert ticket.status is TicketStatus.CREATED
    assert len(adapter.calls) == 2


async def test_always_fail_never_reports_success() -> None:
    adapter = MockTicketingAdapter(always_fail=True)
    for _ in range(3):
        with pytest.raises(TicketCreationError):
            await adapter.create_ticket(_request())
    assert adapter.tickets == {}


async def test_failure_message_is_safe() -> None:
    adapter = MockTicketingAdapter(always_fail=True)
    with pytest.raises(TicketCreationError) as excinfo:
        await adapter.create_ticket(_request(summary="secret sku"))
    assert "secret sku" not in excinfo.value.message


class TestFactory:
    def test_mock_provider(self) -> None:
        adapter = create_ticketing_adapter(TicketingProvider.mock)
        assert isinstance(adapter, MockTicketingAdapter)

    def test_none_provider_always_fails(self) -> None:
        adapter = create_ticketing_adapter(TicketingProvider.none)
        assert isinstance(adapter, MockTicketingAdapter)

    def test_jira_requires_config(self) -> None:
        with pytest.raises(ConfigurationError):
            create_ticketing_adapter(TicketingProvider.jira)

    def test_servicenow_requires_config(self) -> None:
        with pytest.raises(ConfigurationError):
            create_ticketing_adapter(TicketingProvider.servicenow)

    def test_unimplemented_provider_fails_loudly(self) -> None:
        with pytest.raises(ConfigurationError):
            create_ticketing_adapter(TicketingProvider.both)
