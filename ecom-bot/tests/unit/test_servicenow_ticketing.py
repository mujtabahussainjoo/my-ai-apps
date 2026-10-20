"""Unit tests for the ServiceNow incident adapter (TASK-033)."""

from __future__ import annotations

import httpx
import pytest

from ecommerce_support.core.config import IntegrationsConfig, TicketingProvider
from ecommerce_support.core.exceptions import (
    ConfigurationError,
    TicketCreationError,
    TicketingError,
)
from ecommerce_support.integrations import (
    ServiceNowTicketingAdapter,
    build_servicenow_payload,
    create_ticketing_adapter,
)
from ecommerce_support.schemas import ExternalTicket, TicketRequest
from ecommerce_support.schemas.enums import Priority, TicketProvider, TicketStatus

_BASE = "https://acme.service-now.com"


def _config(**overrides: object) -> IntegrationsConfig:
    data: dict[str, object] = {
        "servicenow_instance": "acme.service-now.com",
        "servicenow_username": "bot",
        "servicenow_password": "s3cr3t",
    }
    data.update(overrides)
    return IntegrationsConfig(**data)


def _request(**overrides: object) -> TicketRequest:
    data: dict[str, object] = {
        "conversation_id": "conv-9",
        "summary": "Refund not received",
        "description": "Email jane@example.com",
        "priority": Priority.HIGH,
        "order_id": "ord-9",
    }
    data.update(overrides)
    return TicketRequest(**data)


def _adapter(handler: httpx.MockTransport) -> ServiceNowTicketingAdapter:
    client = httpx.AsyncClient(base_url=_BASE, transport=handler)
    return ServiceNowTicketingAdapter.from_config(_config(), client=client)


class TestPayloadBuilder:
    def test_redacts_and_maps_urgency(self) -> None:
        payload = build_servicenow_payload(_request())
        assert payload["urgency"] == "1"
        assert "jane@example.com" not in str(payload["description"])
        assert "Order: conv-1" not in str(payload["description"])

    def test_redaction_toggle(self) -> None:
        payload = build_servicenow_payload(_request(), redact=False)
        assert "acme" not in str(payload["short_description"])  # summary is plain


class TestCreateTicket:
    async def test_confirmed_creation(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("authorization")
            return httpx.Response(201, json={"result": {"sys_id": "abc123", "number": "INC001"}})

        adapter = _adapter(httpx.MockTransport(handler))
        ticket = await adapter.create_ticket(_request())
        assert isinstance(ticket, ExternalTicket)
        assert ticket.provider is TicketProvider.SERVICENOW
        assert ticket.external_id == "abc123"
        assert ticket.status is TicketStatus.CREATED
        assert "sys_id=abc123" in str(ticket.url)
        assert captured["url"] == f"{_BASE}/api/now/table/incident"
        assert captured["auth"] and str(captured["auth"]).startswith("Basic ")
        await adapter.aclose()

    async def test_non_2xx_is_a_creation_failure(self) -> None:
        adapter = _adapter(httpx.MockTransport(lambda _: httpx.Response(401, json={})))
        with pytest.raises(TicketCreationError) as excinfo:
            await adapter.create_ticket(_request())
        assert excinfo.value.code == "ticket_creation_failed"
        assert excinfo.value.details["status_code"] == 401
        await adapter.aclose()

    async def test_missing_sys_id_is_a_creation_failure(self) -> None:
        adapter = _adapter(httpx.MockTransport(lambda _: httpx.Response(201, json={"result": {}})))
        with pytest.raises(TicketCreationError):
            await adapter.create_ticket(_request())
        await adapter.aclose()

    async def test_transport_error_is_a_creation_failure(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        adapter = _adapter(httpx.MockTransport(handler))
        with pytest.raises(TicketCreationError):
            await adapter.create_ticket(_request())
        await adapter.aclose()

    async def test_failure_message_hides_credentials(self) -> None:
        adapter = _adapter(httpx.MockTransport(lambda _: httpx.Response(500)))
        with pytest.raises(TicketCreationError) as excinfo:
            await adapter.create_ticket(_request())
        assert "s3cr3t" not in excinfo.value.message
        await adapter.aclose()


class TestGetStatus:
    @pytest.mark.parametrize(
        ("state", "expected"),
        [
            ("1", TicketStatus.CREATED),
            ("2", TicketStatus.IN_PROGRESS),
            ("6", TicketStatus.RESOLVED),
        ],
    )
    async def test_maps_state(self, state: str, expected: TicketStatus) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"result": {"state": state, "short_description": "x"}})

        adapter = _adapter(httpx.MockTransport(handler))
        ticket = await adapter.get_status("abc123")
        assert ticket is not None
        assert ticket.status is expected
        await adapter.aclose()

    async def test_unknown_returns_none(self) -> None:
        adapter = _adapter(httpx.MockTransport(lambda _: httpx.Response(404)))
        assert await adapter.get_status("missing") is None
        await adapter.aclose()

    async def test_unexpected_status_raises(self) -> None:
        adapter = _adapter(httpx.MockTransport(lambda _: httpx.Response(503)))
        with pytest.raises(TicketingError):
            await adapter.get_status("abc123")
        await adapter.aclose()


class TestConfigAndFactory:
    def test_from_config_requires_credentials(self) -> None:
        with pytest.raises(ConfigurationError) as excinfo:
            ServiceNowTicketingAdapter.from_config(_config(servicenow_password=None))
        assert "servicenow_password" in excinfo.value.details["missing"]

    def test_factory_builds_servicenow(self) -> None:
        adapter = create_ticketing_adapter(TicketingProvider.servicenow, config=_config())
        assert isinstance(adapter, ServiceNowTicketingAdapter)

    def test_factory_requires_config(self) -> None:
        with pytest.raises(ConfigurationError):
            create_ticketing_adapter(TicketingProvider.servicenow)


def test_payload_urgency_mapping() -> None:
    assert build_servicenow_payload(_request(priority=Priority.LOW))["urgency"] == "3"
    assert build_servicenow_payload(_request(priority=Priority.MEDIUM))["urgency"] == "2"
    assert build_servicenow_payload(_request(priority=Priority.URGENT))["urgency"] == "1"
