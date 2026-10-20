"""End-to-end escalation: worker failure -> ticket creation, idempotency, and failure handling."""

from __future__ import annotations

from typing import Any

import pytest

from ecommerce_support.schemas import ChatRequest
from ecommerce_support.schemas.enums import ConversationStatus, TicketProvider, TicketStatus

pytestmark = pytest.mark.e2e


def _fail_policy_worker(stack: Any) -> None:
    async def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("kaboom")

    stack.graph._policy.answer = _boom


async def _chat(stack: Any, message: str, **kwargs: object):
    request = ChatRequest(message=message, **kwargs)
    return await stack.chat.chat(request, user_id="cust-1")


class TestEscalationCreatesTicket:
    async def test_worker_failure_creates_ticket(self, e2e_stack: Any) -> None:
        _fail_policy_worker(e2e_stack)
        response = await _chat(e2e_stack, "What is your refund policy?")

        assert "support ticket" in response.message.content
        tickets = list(e2e_stack.tickets_store.rows.values())
        assert len(tickets) == 1
        assert tickets[0].status is TicketStatus.CREATED
        assert tickets[0].external_id
        assert len(e2e_stack.adapter.calls) == 1

    async def test_conversation_flagged_ticket_created(self, e2e_stack: Any) -> None:
        _fail_policy_worker(e2e_stack)
        response = await _chat(e2e_stack, "What is your refund policy?")
        stored = e2e_stack.conversations_store.conversations[response.conversation_id]
        assert stored.status is ConversationStatus.TICKET_CREATED

    async def test_ticket_creation_is_audited(self, e2e_stack: Any) -> None:
        _fail_policy_worker(e2e_stack)
        await _chat(e2e_stack, "What is your refund policy?")
        events = [e.event_type for e in e2e_stack.audit.rows]
        assert "ticket.created" in events
        assert e2e_stack.adapter.provider is TicketProvider.MOCK

    async def test_repeat_escalation_reuses_ticket(self, e2e_stack: Any) -> None:
        _fail_policy_worker(e2e_stack)
        first = await _chat(e2e_stack, "What is your refund policy?")
        second = await _chat(
            e2e_stack,
            "Still broken, please escalate.",
            conversation_id=first.conversation_id,
        )
        assert len(e2e_stack.tickets_store.rows) == 1
        assert len(e2e_stack.adapter.calls) == 1
        assert second.conversation_id == first.conversation_id


class TestTicketFailureIsContained:
    async def test_provider_outage_returns_graceful_message(
        self, e2e_stack_failing_tickets: Any
    ) -> None:
        stack = e2e_stack_failing_tickets
        _fail_policy_worker(stack)
        response = await _chat(stack, "What is your refund policy?")
        assert "ticket" in response.message.content.lower()
        stored = stack.conversations_store.conversations[response.conversation_id]
        assert stored.status is ConversationStatus.TICKET_CREATION_FAILED
        failed = [t for t in stack.tickets_store.rows.values() if t.status is TicketStatus.FAILED]
        assert failed
