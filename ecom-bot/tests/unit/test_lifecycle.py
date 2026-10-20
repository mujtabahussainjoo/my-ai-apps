"""Unit tests for the conversation lifecycle state machine (FR-047)."""

from __future__ import annotations

import pytest

from ecommerce_support.core.exceptions import InvalidStateTransition
from ecommerce_support.schemas.enums import ConversationStatus as CS
from ecommerce_support.workflows import lifecycle


class TestHappyPath:
    def test_open_to_resolved(self) -> None:
        code = CS.OPEN
        for target in (CS.IN_PROGRESS, CS.AWAITING_CUSTOMER, CS.RESOLVED):
            code = lifecycle.transition(code, target)
        assert code is CS.RESOLVED

    def test_escalation_branch(self) -> None:
        code = lifecycle.transition(CS.IN_PROGRESS, CS.ESCALATION_PENDING)
        code = lifecycle.transition(code, CS.TICKET_CREATED)
        assert code is CS.TICKET_CREATED

    def test_ticket_failure_reachable(self) -> None:
        code = lifecycle.transition(CS.ESCALATION_PENDING, CS.TICKET_CREATION_FAILED)
        assert lifecycle.can_transition(code, CS.ESCALATION_PENDING)


class TestRules:
    def test_illegal_transition_raises(self) -> None:
        with pytest.raises(InvalidStateTransition) as excinfo:
            lifecycle.transition(CS.OPEN, CS.RESOLVED)
        assert excinfo.value.code == "invalid_state_transition"
        assert excinfo.value.http_status == 409

    def test_resolved_is_terminal(self) -> None:
        assert lifecycle.transitions_from(CS.RESOLVED) == frozenset()
        assert lifecycle.can_transition(CS.RESOLVED, CS.IN_PROGRESS) is False

    def test_no_self_transitions(self) -> None:
        for state in CS:
            assert lifecycle.can_transition(state, state) is False

    def test_terminal_states(self) -> None:
        assert frozenset({CS.RESOLVED, CS.ABANDONED}) == lifecycle.TERMINAL_STATES

    @pytest.mark.parametrize("state", list(CS))
    def test_every_state_has_transition_entry(self, state: CS) -> None:
        assert isinstance(lifecycle.transitions_from(state), frozenset)

    def test_every_target_is_a_real_state(self) -> None:
        for state in CS:
            for target in lifecycle.transitions_from(state):
                assert isinstance(target, CS)
