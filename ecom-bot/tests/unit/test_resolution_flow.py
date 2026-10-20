"""Unit tests for the customer resolution-confirmation flow (TASK-029, FR-046/FR-047)."""

from __future__ import annotations

import pytest

from ecommerce_support.core.config import AgentsConfig
from ecommerce_support.core.exceptions import InvalidStateTransition
from ecommerce_support.schemas.enums import (
    Confirmation,
    ResolutionOutcome,
)
from ecommerce_support.schemas.enums import (
    ConversationStatus as CS,
)
from ecommerce_support.workflows import ResolutionFlow, interpret_confirmation


@pytest.mark.parametrize(
    "message",
    ["yes", "Yes please", "yep", "that worked", "it's fixed, thanks", "solved", "perfect"],
)
def test_interpret_yes(message: str) -> None:
    assert interpret_confirmation(message) is Confirmation.YES


@pytest.mark.parametrize(
    "message",
    [
        "no",
        "nope",
        "not resolved",
        "still not working",
        "it didn't work",
        "same issue",
        "unresolved",
    ],
)
def test_interpret_no(message: str) -> None:
    assert interpret_confirmation(message) is Confirmation.NO


@pytest.mark.parametrize("message", ["", "maybe", "hmm", "what do you mean?"])
def test_interpret_unknown(message: str) -> None:
    assert interpret_confirmation(message) is Confirmation.UNKNOWN


def test_negative_wins_over_positive() -> None:
    assert interpret_confirmation("no, not resolved") is Confirmation.NO
    assert interpret_confirmation("thanks but it's still not working") is Confirmation.NO


class TestBegin:
    def test_open_advances_to_awaiting(self) -> None:
        step = ResolutionFlow().begin(CS.OPEN)
        assert step.status is CS.AWAITING_CUSTOMER

    def test_in_progress_advances_to_awaiting(self) -> None:
        assert ResolutionFlow().begin(CS.IN_PROGRESS).status is CS.AWAITING_CUSTOMER

    def test_already_awaiting_stays(self) -> None:
        assert ResolutionFlow().begin(CS.AWAITING_CUSTOMER).status is CS.AWAITING_CUSTOMER


class TestApply:
    def test_yes_resolves(self) -> None:
        step = ResolutionFlow().apply(CS.AWAITING_CUSTOMER, "yes")
        assert step.status is CS.RESOLVED
        assert step.outcome is ResolutionOutcome.RESOLVED
        assert step.escalate is False

    def test_no_retries_while_attempts_remain(self) -> None:
        step = ResolutionFlow(AgentsConfig(max_retry_attempts=2)).apply(
            CS.AWAITING_CUSTOMER, "no", retry_count=0
        )
        assert step.status is CS.IN_PROGRESS
        assert step.outcome is ResolutionOutcome.UNRESOLVED
        assert step.escalate is False
        assert step.message

    def test_no_escalates_when_exhausted(self) -> None:
        step = ResolutionFlow(AgentsConfig(max_retry_attempts=2)).apply(
            CS.AWAITING_CUSTOMER, "no", retry_count=2
        )
        assert step.status is CS.ESCALATION_PENDING
        assert step.escalate is True

    def test_no_escalates_when_retries_disabled(self) -> None:
        step = ResolutionFlow(AgentsConfig(max_retry_attempts=0)).apply(CS.AWAITING_CUSTOMER, "no")
        assert step.status is CS.ESCALATION_PENDING
        assert step.escalate is True

    def test_unknown_asks_again(self) -> None:
        step = ResolutionFlow().apply(CS.AWAITING_CUSTOMER, "hmm")
        assert step.status is CS.AWAITING_CUSTOMER
        assert step.ask_again is True
        assert step.confirmation is Confirmation.UNKNOWN

    def test_illegal_transition_from_resolved(self) -> None:
        with pytest.raises(InvalidStateTransition):
            ResolutionFlow().apply(CS.RESOLVED, "no")
