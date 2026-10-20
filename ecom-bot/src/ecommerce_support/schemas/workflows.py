"""Workflow-layer contracts (resolution + ticket lifecycles).

Framework-free Pydantic models that services and API layers pass around. Keeping them here avoids
importing graph/agent internals from transport code.
"""

from __future__ import annotations

from ecommerce_support.schemas.common import Schema
from ecommerce_support.schemas.enums import Confirmation, ConversationStatus, ResolutionOutcome


class ResolutionStep(Schema):
    """Result of handling one customer turn in the resolution loop.

    ``status`` is the transitioned conversation state (validated by the FR-047 state machine),
    ``escalate`` signals the caller to start the ticket flow, and ``ask_again`` asks the customer a
    second time when their reply was not a clear yes/no.
    """

    status: ConversationStatus
    outcome: ResolutionOutcome
    confirmation: Confirmation
    escalate: bool = False
    ask_again: bool = False
    message: str = ""
