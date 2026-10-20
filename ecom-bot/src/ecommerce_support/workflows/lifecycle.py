"""Conversation lifecycle state machine (FR-047).

Pure, framework-free transition rules for ``ConversationStatus``. Services enforce these in code
(never prompts): an illegal transition raises :class:`InvalidStateTransition`. The happy path is
``OPEN → IN_PROGRESS → AWAITING_CUSTOMER → RESOLVED``; unresolved issues branch to
``ESCALATION_PENDING → TICKET_CREATED`` with ``TICKET_CREATION_FAILED`` as the failure state.
"""

from __future__ import annotations

from ecommerce_support.core.exceptions import InvalidStateTransition
from ecommerce_support.schemas.enums import ConversationStatus

OPEN = ConversationStatus.OPEN
IN_PROGRESS = ConversationStatus.IN_PROGRESS
AWAITING_CUSTOMER = ConversationStatus.AWAITING_CUSTOMER
RESOLVED = ConversationStatus.RESOLVED
ESCALATION_PENDING = ConversationStatus.ESCALATION_PENDING
TICKET_CREATED = ConversationStatus.TICKET_CREATED
TICKET_CREATION_FAILED = ConversationStatus.TICKET_CREATION_FAILED
ABANDONED = ConversationStatus.ABANDONED
ERROR = ConversationStatus.ERROR

_TRANSITIONS: dict[ConversationStatus, frozenset[ConversationStatus]] = {
    OPEN: frozenset({IN_PROGRESS, ABANDONED}),
    IN_PROGRESS: frozenset({AWAITING_CUSTOMER, RESOLVED, ESCALATION_PENDING, ABANDONED, ERROR}),
    AWAITING_CUSTOMER: frozenset({IN_PROGRESS, RESOLVED, ESCALATION_PENDING, ABANDONED, ERROR}),
    ESCALATION_PENDING: frozenset(
        {TICKET_CREATED, TICKET_CREATION_FAILED, AWAITING_CUSTOMER, ABANDONED}
    ),
    TICKET_CREATED: frozenset({RESOLVED, ABANDONED}),
    TICKET_CREATION_FAILED: frozenset({ESCALATION_PENDING, IN_PROGRESS, ABANDONED, ERROR}),
    RESOLVED: frozenset(),
    ABANDONED: frozenset(),
    ERROR: frozenset({IN_PROGRESS, ESCALATION_PENDING, ABANDONED}),
}

TERMINAL_STATES: frozenset[ConversationStatus] = frozenset({RESOLVED, ABANDONED})


def transitions_from(current: ConversationStatus) -> frozenset[ConversationStatus]:
    """Return the set of legal target states from ``current``."""
    return _TRANSITIONS[current]


def can_transition(current: ConversationStatus, target: ConversationStatus) -> bool:
    """Whether moving ``current`` → ``target`` is allowed by the state machine."""
    return target in _TRANSITIONS[current]


def transition(current: ConversationStatus, target: ConversationStatus) -> ConversationStatus:
    """Validate and return ``target``, raising :class:`InvalidStateTransition` otherwise."""
    if not can_transition(current, target):
        raise InvalidStateTransition(
            f"Cannot move conversation from {current} to {target}.",
            details={"current": current.value, "target": target.value},
        )
    return target


def is_terminal(state: ConversationStatus) -> bool:
    """Whether ``state`` is a terminal lifecycle state."""
    return state in TERMINAL_STATES
