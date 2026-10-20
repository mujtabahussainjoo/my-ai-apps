"""Tests for token/cost tracking (TASK-015)."""

from __future__ import annotations

import pytest

from ecommerce_support.llm.types import Usage
from ecommerce_support.llm.usage import (
    MODEL_PRICING,
    UsageTracker,
    estimate_cost,
    get_usage_tracker,
    price_for,
    reset_usage_tracker,
)


def test_price_for_exact_match() -> None:
    assert price_for("gpt-4o") == MODEL_PRICING["gpt-4o"]


def test_price_for_prefix_match_prefers_longest() -> None:
    # Dated snapshot resolves to the base model.
    assert price_for("claude-sonnet-4-5-20250929") == MODEL_PRICING["claude-sonnet-4-5"]


def test_price_for_unknown_returns_none() -> None:
    assert price_for("totally-unknown-model") is None


def test_estimate_cost_uses_input_and_output_rates() -> None:
    usage = Usage(prompt_tokens=1_000_000, completion_tokens=1_000_000, total_tokens=2_000_000)
    input_price, output_price = MODEL_PRICING["gpt-4o"]
    assert estimate_cost("gpt-4o", usage) == pytest.approx(input_price + output_price)


def test_estimate_cost_unknown_model_is_zero() -> None:
    usage = Usage(prompt_tokens=100, completion_tokens=100, total_tokens=200)
    assert estimate_cost("mystery", usage) == 0.0


def test_tracker_records_and_aggregates() -> None:
    tracker = UsageTracker()
    tracker.record(
        provider="mock",
        model="gpt-4o",
        usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    tracker.record(
        provider="mock",
        model="gpt-4o",
        usage=Usage(prompt_tokens=20, completion_tokens=10, total_tokens=30),
    )
    totals = tracker.totals()
    assert totals.calls == 2
    assert totals.prompt_tokens == 30
    assert totals.completion_tokens == 15
    assert totals.total_tokens == 45
    assert totals.cost_usd > 0


def test_tracker_totals_filter_by_model() -> None:
    tracker = UsageTracker()
    tracker.record(
        provider="p",
        model="gpt-4o",
        usage=Usage(prompt_tokens=10, completion_tokens=0, total_tokens=10),
    )
    tracker.record(
        provider="p",
        model="claude-sonnet-4-5",
        usage=Usage(prompt_tokens=100, completion_tokens=0, total_tokens=100),
    )
    assert tracker.totals(model="gpt-4o").total_tokens == 10
    assert tracker.totals(model="claude-sonnet-4-5").total_tokens == 100
    assert tracker.totals().total_tokens == 110


def test_tracker_record_fields_and_ordering() -> None:
    tracker = UsageTracker()
    first = tracker.record(
        provider="anthropic",
        model="claude-sonnet-4-5",
        usage=Usage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
    )
    second = tracker.record(
        provider="anthropic",
        model="claude-sonnet-4-5",
        usage=Usage(prompt_tokens=4, completion_tokens=5, total_tokens=9),
    )
    assert first.provider == "anthropic"
    assert first.total_tokens == 3
    assert first.recorded_at <= second.recorded_at
    assert tracker.records() == [first, second]


def test_records_returns_a_copy() -> None:
    tracker = UsageTracker()
    tracker.record(provider="p", model="m", usage=Usage())
    snapshot = tracker.records()
    snapshot.clear()
    assert len(tracker.records()) == 1


def test_tracker_reset() -> None:
    tracker = UsageTracker()
    tracker.record(provider="p", model="m", usage=Usage(total_tokens=5))
    tracker.reset()
    assert tracker.records() == []
    assert tracker.totals().calls == 0


def test_default_tracker_singleton() -> None:
    reset_usage_tracker()
    assert get_usage_tracker() is get_usage_tracker()
    get_usage_tracker().record(provider="p", model="m", usage=Usage(total_tokens=1))
    assert get_usage_tracker().totals().calls == 1
    reset_usage_tracker()
    assert get_usage_tracker().totals().calls == 0
