"""Unit tests for the Jira ticketing adapter and redacted payload builder (TASK-032)."""

from __future__ import annotations

import httpx
import pytest

from ecommerce_support.core.config import IntegrationsConfig, TicketingProvider
from ecommerce_support.core.exceptions import (
    ConfigurationError,
    TicketCreationError,
    TicketingError,
)
from ecommerce_support.guardrails.redaction import redact_text
from ecommerce_support.integrations import (
    JiraTicketingAdapter,
    build_jira_payload,
    create_ticketing_adapter,
)
from ecommerce_support.schemas import ExternalTicket, TicketRequest
from ecommerce_support.schemas.enums import Priority, TicketProvider, TicketStatus

_BASE = "https://acme.atlassian.net"


def _config(**overrides: object) -> IntegrationsConfig:
    data: dict[str, object] = {
        "jira_base_url": _BASE,
        "jira_email": "bot@acme.test",
        "jira_api_token": "super-secret-token",
        "jira_project_key": "SUP",
        "jira_issue_type": "Bug",
    }
    data.update(overrides)
    return IntegrationsConfig(**data)


def _request(**overrides: object) -> TicketRequest:
    data: dict[str, object] = {
        "conversation_id": "conv 1",
        "summary": "Order never arrived",
        "description": "Reach me at jane@example.com or 4111111111111111.",
        "priority": Priority.URGENT,
        "order_id": "ord-1",
        "product_ids": ["prd-2"],
        "expected_behavior": "Delivery in 3 days",
        "actual_behavior": "Nothing shipped",
        "steps_attempted": ["checked tracking"],
    }
    data.update(overrides)
    return TicketRequest(**data)


def _adapter(handler: httpx.MockTransport) -> JiraTicketingAdapter:
    client = httpx.AsyncClient(base_url=_BASE, transport=handler)
    return JiraTicketingAdapter.from_config(_config(), client=client)


class TestPayloadBuilder:
    def test_redacts_free_text(self) -> None:
        payload = build_jira_payload(_request(), project_key="SUP")
        fields = payload["fields"]
        assert isinstance(fields, dict)
        description = str(fields["description"])
        assert "jane@example.com" not in description
        assert "4111111111111111" not in description
        assert "***" not in description  # uses a plain marker, not logs' marker

    def test_contains_context(self) -> None:
        payload = build_jira_payload(_request(), project_key="SUP")
        fields = payload["fields"]
        assert fields["project"] == {"key": "SUP"}
        assert fields["issuetype"] == {"name": "Task"}
        assert fields["priority"] == {"name": "Highest"}
        description = str(fields["description"])
        assert "Order: ord-1" in description
        assert "Products: prd-2" in description
        assert "Expected: Delivery in 3 days" in description

    def test_labels_are_sanitised(self) -> None:
        payload = build_jira_payload(_request(), project_key="SUP")
        fields = payload["fields"]
        labels = fields["labels"]
        assert isinstance(labels, list)
        assert "ecom-support" in labels
        assert any(label.startswith("conv-") for label in labels)
        assert all(" " not in label for label in labels)

    def test_redaction_can_be_disabled(self) -> None:
        payload = build_jira_payload(_request(), project_key="SUP", redact=False)
        fields = payload["fields"]
        assert "jane@example.com" in str(fields["description"])


class TestCreateTicket:
    async def test_confirmed_creation(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["auth"] = request.headers.get("authorization")
            return httpx.Response(201, json={"id": "10001", "key": "SUP-7"})

        adapter = _adapter(httpx.MockTransport(handler))
        ticket = await adapter.create_ticket(_request())
        assert isinstance(ticket, ExternalTicket)
        assert ticket.provider is TicketProvider.JIRA
        assert ticket.external_id == "SUP-7"
        assert ticket.status is TicketStatus.CREATED
        assert ticket.url == f"{_BASE}/browse/SUP-7"
        assert captured["url"] == f"{_BASE}/rest/api/2/issue"
        assert captured["auth"] and str(captured["auth"]).startswith("Basic ")
        await adapter.aclose()

    async def test_non_2xx_is_a_creation_failure(self) -> None:
        adapter = _adapter(httpx.MockTransport(lambda _: httpx.Response(400, json={})))
        with pytest.raises(TicketCreationError) as excinfo:
            await adapter.create_ticket(_request())
        assert excinfo.value.code == "ticket_creation_failed"
        assert excinfo.value.details["status_code"] == 400
        await adapter.aclose()

    async def test_missing_key_is_a_creation_failure(self) -> None:
        adapter = _adapter(httpx.MockTransport(lambda _: httpx.Response(201, json={"id": "1"})))
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
        assert "super-secret-token" not in excinfo.value.message
        await adapter.aclose()


class TestGetStatus:
    async def test_maps_status(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "key": "SUP-7",
                    "fields": {"status": {"name": "In Progress"}, "summary": "x"},
                },
            )

        adapter = _adapter(httpx.MockTransport(handler))
        ticket = await adapter.get_status("SUP-7")
        assert ticket is not None
        assert ticket.status is TicketStatus.IN_PROGRESS
        await adapter.aclose()

    async def test_unknown_returns_none(self) -> None:
        adapter = _adapter(httpx.MockTransport(lambda _: httpx.Response(404)))
        assert await adapter.get_status("SUP-404") is None
        await adapter.aclose()

    async def test_unexpected_status_raises(self) -> None:
        adapter = _adapter(httpx.MockTransport(lambda _: httpx.Response(503)))
        with pytest.raises(TicketingError):
            await adapter.get_status("SUP-7")
        await adapter.aclose()


class TestConfigAndFactory:
    def test_from_config_requires_secrets(self) -> None:
        with pytest.raises(ConfigurationError) as excinfo:
            JiraTicketingAdapter.from_config(_config(jira_api_token=None))
        assert "jira_api_token" in excinfo.value.details["missing"]

    def test_factory_builds_jira(self) -> None:
        adapter = create_ticketing_adapter(TicketingProvider.jira, config=_config())
        assert isinstance(adapter, JiraTicketingAdapter)


def test_redact_text_covers_common_secrets() -> None:
    assert "4111" not in redact_text("card 4111 1111 1111 1111")
    assert "jane@example.com" not in redact_text("mail jane@example.com")
    assert "sk-live-123456" not in redact_text("key sk-live-123456")
