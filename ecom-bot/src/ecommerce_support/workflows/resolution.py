"""Resolution-confirmation flow (FR-046/FR-047/FR-048).

The chat service uses this module to close the loop after an answer: it asks whether the issue is
resolved, interprets the customer's reply, and drives the FR-047 state machine. Free-text
interpretation is deliberately conservative (an explicit "no" wins over a stray "yes") and only
clear signals advance the lifecycle — anything else asks the customer again.
"""

from __future__ import annotations

import re

from ecommerce_support.core.config import AgentsConfig
from ecommerce_support.schemas.enums import Confirmation, ConversationStatus, ResolutionOutcome
from ecommerce_support.schemas.workflows import ResolutionStep
from ecommerce_support.workflows.lifecycle import can_transition, transition

_YES_TOKENS = frozenset(
    {
        "yes",
        "yep",
        "yeah",
        "yup",
        "y",
        "solved",
        "resolved",
        "fixed",
        "worked",
        "perfect",
        "great",
        "thanks",
        "thank",
        "correct",
        "done",
    }
)
_YES_PHRASES = ("that worked", "it worked", "all good", "that's it")
_NO_PHRASES = (
    "not resolved",
    "not fixed",
    "not yet",
    "still not",
    "doesn't work",
    "doesnt work",
    "didn't work",
    "didnt work",
    "does not work",
    "did not work",
    "same issue",
    "same problem",
    "not working",
)
_NO_WORDS = frozenset({"no", "nope", "nah", "unresolved"})

_ASK_AGAIN = "Sorry — just so I get this right: did that resolve your issue? (yes/no)"
_RETRY_MESSAGE = "Sorry about that — let me take another look."
_ESCALATE_MESSAGE = "I'll escalate this to a human agent now."


def interpret_confirmation(message: str) -> Confirmation:
    """Classify a free-text reply as an explicit yes, explicit no, or unclear.

    Negative signals win over positive ones so a phrase like "no, not resolved" is never mistaken
    for success (answered "thanks" after an unrelated word is still treated as unknown unless it is
    a clear token).
    """
    text = re.sub(r"[^\w\s']", " ", message.lower())
    tokens = text.split()
    normalized = " ".join(tokens)
    if not tokens:
        return Confirmation.UNKNOWN

    if any(phrase in normalized for phrase in _NO_PHRASES) or any(
        token in _NO_WORDS for token in tokens
    ):
        return Confirmation.NO
    if any(phrase in normalized for phrase in _YES_PHRASES) or any(
        token in _YES_TOKENS for token in tokens
    ):
        return Confirmation.YES
    return Confirmation.UNKNOWN


class ResolutionFlow:
    """Drives the customer-confirmation side of the resolution lifecycle."""

    def __init__(self, config: AgentsConfig | None = None) -> None:
        self._config = config or AgentsConfig()

    def begin(self, current: ConversationStatus) -> ResolutionStep:
        """Advance to ``AWAITING_CUSTOMER`` after an answer was sent (IN_PROGRESS → AWAITING)."""
        if current is ConversationStatus.AWAITING_CUSTOMER:
            return ResolutionStep(
                status=current,
                outcome=ResolutionOutcome.UNRESOLVED,
                confirmation=Confirmation.UNKNOWN,
            )
        status: ConversationStatus = current
        if current is ConversationStatus.OPEN:
            status = transition(current, ConversationStatus.IN_PROGRESS)
        if status is ConversationStatus.IN_PROGRESS:
            status = transition(status, ConversationStatus.AWAITING_CUSTOMER)
        return ResolutionStep(
            status=status, outcome=ResolutionOutcome.UNRESOLVED, confirmation=Confirmation.UNKNOWN
        )

    def apply(
        self,
        current: ConversationStatus,
        message: str,
        *,
        retry_count: int = 0,
    ) -> ResolutionStep:
        """Handle the customer's reply to the resolution prompt and transition accordingly."""
        confirmation = interpret_confirmation(message)

        if confirmation is Confirmation.YES:
            return ResolutionStep(
                status=transition(current, ConversationStatus.RESOLVED),
                outcome=ResolutionOutcome.RESOLVED,
                confirmation=confirmation,
            )

        if confirmation is Confirmation.NO:
            if retry_count < self._config.max_retry_attempts and can_transition(
                current, ConversationStatus.IN_PROGRESS
            ):
                return ResolutionStep(
                    status=transition(current, ConversationStatus.IN_PROGRESS),
                    outcome=ResolutionOutcome.UNRESOLVED,
                    confirmation=confirmation,
                    message=_RETRY_MESSAGE,
                )
            return ResolutionStep(
                status=transition(current, ConversationStatus.ESCALATION_PENDING),
                outcome=ResolutionOutcome.UNRESOLVED,
                confirmation=confirmation,
                escalate=True,
                message=_ESCALATE_MESSAGE,
            )

        return ResolutionStep(
            status=current,
            outcome=ResolutionOutcome.UNRESOLVED,
            confirmation=Confirmation.UNKNOWN,
            ask_again=True,
            message=_ASK_AGAIN,
        )
