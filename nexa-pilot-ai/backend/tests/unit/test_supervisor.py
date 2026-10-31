"""Supervisor routing tests."""

from __future__ import annotations

import pytest

from nexapilot.agents.supervisor import classify_request, validate_workflow


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("Search the web for the latest news about Python 3.14", "research"),
        ("Find me a flight from SFO to JFK on 2026-03-01", "travel"),
        ("Read my email and summarise what needs a reply", "email"),
        ("What is on my calendar tomorrow?", "calendar"),
        ("Check the price of AAPL and my portfolio", "finance"),
        ("Write a Python script that sorts a list and run it", "coding"),
        ("Hello there", "general"),
    ],
)
def test_classification_targets(prompt: str, expected: str) -> None:
    decision = classify_request(prompt)
    assert decision.workflow == expected


def test_decision_reports_signals() -> None:
    decision = classify_request("Search the web for OpenAI release notes")
    assert decision.workflow == "research"
    assert decision.matched
    assert 0.0 <= decision.confidence <= 1.0


def test_validate_workflow_normalises_unknown_values() -> None:
    assert validate_workflow("research") == "research"
    assert validate_workflow("not-a-workflow") == "general"
    assert validate_workflow("") == "general"
