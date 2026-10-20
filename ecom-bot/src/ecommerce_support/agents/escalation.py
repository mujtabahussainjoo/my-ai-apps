"""Escalation agent: turn an unresolved workflow state into a typed ticket request (FR-025).

Framework-free. The graph flags ``escalation_requested``; this agent assembles the structured,
redaction-ready :class:`TicketRequest` that :class:`~ecommerce_support.services.tickets.TicketService`
then dispatches through the configured ticketing adapter. Keeping payload assembly here (not in the
transport) makes it unit-testable and consistent across Jira/ServiceNow.
"""

from __future__ import annotations

from ecommerce_support.schemas.agents import AgentState
from ecommerce_support.schemas.enums import Priority
from ecommerce_support.schemas.tickets import TicketRequest

_DEFAULT_SUMMARY = "Customer requested human support."
_MAX_SUMMARY = 255


class EscalationAgent:
    """Builds ticket requests from the workflow state."""

    def __init__(self, *, max_summary_chars: int = _MAX_SUMMARY) -> None:
        self._max_summary = max_summary_chars

    def summarize(self, state: AgentState) -> str:
        """A one-line, length-bounded summary derived from the customer's message."""
        for line in state.message.splitlines():
            cleaned = line.strip()
            if cleaned:
                return cleaned[: self._max_summary]
        return _DEFAULT_SUMMARY

    def describe(self, state: AgentState) -> str:
        """The assignee-facing description: the customer's message plus why it stayed unresolved."""
        parts = [state.message.strip()]
        if state.error:
            parts.append(f"Unresolved reason: {state.error}")
        return "\n\n".join(part for part in parts if part)

    def build_request(self, state: AgentState) -> TicketRequest:
        """Assemble a :class:`TicketRequest` for the escalation."""
        return TicketRequest(
            conversation_id=state.conversation_id,
            summary=self.summarize(state),
            description=self.describe(state),
            priority=Priority.HIGH if state.error else Priority.MEDIUM,
            steps_attempted=list(state.attempts),
            sources=list(state.evidence),
            actual_behavior=state.error,
            requires_confirmation=False,
        )


__all__ = ["EscalationAgent"]
