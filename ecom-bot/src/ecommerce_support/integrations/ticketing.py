"""Ticketing adapter contracts + mock integration (FR-041/FR-043/FR-044, INT-004).

The external ticketing backend sits behind :class:`TicketingAdapter`. v1 ships a mock adapter; Jira
and ServiceNow adapters are documented extension points implemented behind the same interface
(TASK-032/033). A ticket is only ever reported as created when the adapter returns a confirmed
:class:`ExternalTicket`; failures raise :class:`TicketCreationError` so the caller can surface
``TICKET_CREATION_FAILED`` honestly (FR-044).

Adapters are plain Python — no framework imports — and return Pydantic schemas.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from ecommerce_support.core.config import IntegrationsConfig, TicketingProvider
from ecommerce_support.core.exceptions import ConfigurationError, TicketCreationError
from ecommerce_support.core.ids import new_id
from ecommerce_support.guardrails.redaction import redact_text
from ecommerce_support.schemas import ExternalTicket, TicketRequest
from ecommerce_support.schemas.enums import TicketProvider, TicketStatus


def build_ticket_description(request: TicketRequest, *, redact: bool = True) -> str:
    """Render a redacted, assignee-oriented description from a :class:`TicketRequest`.

    Shared by provider payload builders (FR-050/FR-051): includes the customer description plus the
    order/product/expected/actual/steps/sources context, and never any credentials or internal
    reasoning. Free text is scrubbed with :func:`redact_text` unless ``redact`` is false.
    """

    def clean(text: str) -> str:
        return redact_text(text) if redact else text

    context: list[str] = []
    if request.order_id:
        context.append(f"Order: {request.order_id}")
    if request.product_ids:
        context.append(f"Products: {', '.join(request.product_ids)}")
    if request.expected_behavior:
        context.append(f"Expected: {clean(request.expected_behavior)}")
    if request.actual_behavior:
        context.append(f"Actual: {clean(request.actual_behavior)}")
    if request.steps_attempted:
        context.append("Steps attempted:")
        context.extend(f"- {clean(step)}" for step in request.steps_attempted)
    if request.sources:
        context.append("Sources:")
        context.extend(
            f"- {source.document_title or source.document_id}"
            + (f" / {source.section_title}" if source.section_title else "")
            for source in request.sources
        )

    description = clean(request.description)
    if context:
        description = f"{description}\n\n" + "\n".join(context)
    return description.strip()


class TicketingAdapter(ABC):
    """Create and query support tickets in an external system."""

    provider: TicketProvider

    @abstractmethod
    async def create_ticket(self, request: TicketRequest) -> ExternalTicket:
        """Create a ticket and return the **confirmed** external reference.

        Must raise :class:`TicketCreationError` (never return a fabricated ticket) when the external
        service does not confirm creation.
        """

    @abstractmethod
    async def get_status(self, external_id: str) -> ExternalTicket | None:
        """Return the current external ticket state, or ``None`` if unknown."""


class MockTicketingAdapter(TicketingAdapter):
    """In-memory ticketing adapter for local/dev/test use (mock, not a real backend).

    Deterministic and configurable: ``fail_next`` simulates transient failures (each call consumes
    one), ``always_fail`` simulates a hard outage. Successful creations are retrievable via
    :meth:`get_status` so idempotency/lifecycle flows can be exercised without a network.
    """

    provider = TicketProvider.MOCK

    def __init__(self, *, fail_next: int = 0, always_fail: bool = False) -> None:
        self._fail_next = max(0, fail_next)
        self._always_fail = always_fail
        self.calls: list[TicketRequest] = []
        self.tickets: dict[str, ExternalTicket] = {}

    def _should_fail(self) -> bool:
        if self._always_fail:
            return True
        if self._fail_next > 0:
            self._fail_next -= 1
            return True
        return False

    def recover(self) -> None:
        """Clear any configured failure mode (simulate the provider recovering)."""
        self._fail_next = 0
        self._always_fail = False

    async def create_ticket(self, request: TicketRequest) -> ExternalTicket:
        self.calls.append(request)
        if self._should_fail():
            raise TicketCreationError(
                "The ticketing service did not confirm ticket creation.",
                details={"provider": self.provider.value},
            )
        external_id = new_id("mock")
        ticket = ExternalTicket(
            provider=self.provider,
            external_id=external_id,
            status=TicketStatus.CREATED,
            url=f"https://mock.tickets.local/{external_id}",
            summary=request.summary,
        )
        self.tickets[external_id] = ticket
        return ticket

    async def get_status(self, external_id: str) -> ExternalTicket | None:
        return self.tickets.get(external_id)


def create_ticketing_adapter(
    provider: TicketingProvider,
    *,
    config: IntegrationsConfig | None = None,
    client: httpx.AsyncClient | None = None,
    fail_next: int = 0,
    always_fail: bool = False,
) -> TicketingAdapter:
    """Build a ticketing adapter for ``provider``.

    ``mock``/``none`` need no configuration; ``jira`` requires an :class:`IntegrationsConfig` and
    fails loudly (``ConfigurationError``) when unset. ServiceNow is not implemented until TASK-033
    and raises rather than silently degrading.
    """
    if provider is TicketingProvider.mock:
        return MockTicketingAdapter(fail_next=fail_next, always_fail=always_fail)
    if provider is TicketingProvider.none:
        return MockTicketingAdapter(always_fail=True)
    if provider is TicketingProvider.jira:
        if config is None:
            raise ConfigurationError(
                "Jira ticketing requires an integrations config.",
                details={"provider": provider.value},
            )
        from ecommerce_support.integrations.jira import JiraTicketingAdapter

        return JiraTicketingAdapter.from_config(config, client=client)
    if provider is TicketingProvider.servicenow:
        if config is None:
            raise ConfigurationError(
                "ServiceNow ticketing requires an integrations config.",
                details={"provider": provider.value},
            )
        from ecommerce_support.integrations.servicenow import ServiceNowTicketingAdapter

        return ServiceNowTicketingAdapter.from_config(config, client=client)
    raise ConfigurationError(
        f"Ticketing provider '{provider.value}' is not implemented yet.",
        details={"provider": provider.value},
    )


__all__ = [
    "MockTicketingAdapter",
    "TicketingAdapter",
    "build_ticket_description",
    "create_ticketing_adapter",
]
