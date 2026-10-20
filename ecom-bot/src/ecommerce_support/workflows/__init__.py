"""Workflow layer: framework-free lifecycle orchestration used by services and the API.

`lifecycle.py` is the FR-047 conversation state machine; `resolution.py` drives the
customer-confirmation loop (FR-046-FR-051). Ticket lifecycle/idempotency lives in
`services/tickets.py` on top of the ticketing adapter.
"""

from ecommerce_support.workflows.lifecycle import (
    TERMINAL_STATES,
    can_transition,
    is_terminal,
    transition,
    transitions_from,
)
from ecommerce_support.workflows.resolution import ResolutionFlow, interpret_confirmation

__all__ = [
    "TERMINAL_STATES",
    "ResolutionFlow",
    "can_transition",
    "interpret_confirmation",
    "is_terminal",
    "transition",
    "transitions_from",
]
