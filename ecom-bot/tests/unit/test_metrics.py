"""Tests for the process-wide metrics registry and Prometheus rendering (FR-055)."""

from __future__ import annotations

import pytest

from ecommerce_support.core.metrics import (
    COUNTER_TOOL_CALLS,
    HISTOGRAM_CHAT_LATENCY,
    Metrics,
    get_metrics,
    record_chat_turn,
    render_prometheus,
    reset_metrics,
)


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_metrics()


def test_counter_increment_and_labels() -> None:
    metrics = Metrics()
    metrics.increment(COUNTER_TOOL_CALLS, tool="get_order", status="ok")
    metrics.increment(COUNTER_TOOL_CALLS, tool="get_order", status="ok")
    metrics.increment(COUNTER_TOOL_CALLS, tool="get_order", status="error")
    assert metrics.counter_value(COUNTER_TOOL_CALLS, tool="get_order", status="ok") == 2.0
    assert metrics.counter_value(COUNTER_TOOL_CALLS, tool="get_order", status="error") == 1.0
    assert metrics.counter_value(COUNTER_TOOL_CALLS, tool="missing", status="ok") == 0.0


def test_histogram_quantiles() -> None:
    metrics = Metrics()
    for value in range(1, 101):
        metrics.observe(HISTOGRAM_CHAT_LATENCY, float(value))
    assert metrics.histogram_samples(HISTOGRAM_CHAT_LATENCY) == [float(i) for i in range(1, 101)]
    snapshot = metrics.snapshot()
    histogram = next(h for h in snapshot["histograms"] if h["name"] == HISTOGRAM_CHAT_LATENCY)
    assert histogram["count"] == 100
    assert histogram["min"] == 1.0
    assert histogram["max"] == 100.0
    assert 49.0 <= histogram["p50"] <= 51.0
    assert 94.0 <= histogram["p95"] <= 96.0


def test_record_chat_turn_updates_counter_and_histogram() -> None:
    record_chat_turn("answered", 0.25)
    record_chat_turn("answered", 0.75)
    metrics = get_metrics()
    assert metrics.counter_value("chat_turns_total", outcome="answered") == 2
    assert metrics.histogram_samples(HISTOGRAM_CHAT_LATENCY) == [0.25, 0.75]


def test_snapshot_is_sorted_and_json_serializable() -> None:
    metrics = Metrics()
    metrics.increment("b_total")
    metrics.increment("a_total", kind="x")
    snapshot = metrics.snapshot()
    names = [counter["name"] for counter in snapshot["counters"]]
    assert names == ["a_total", "b_total"]


def test_render_prometheus_contains_counters_and_histograms() -> None:
    metrics = Metrics()
    metrics.increment(COUNTER_TOOL_CALLS, tool="get_order", status="ok")
    metrics.observe(HISTOGRAM_CHAT_LATENCY, 0.5)
    text = render_prometheus(metrics)
    assert 'tool_calls_total{status="ok",tool="get_order"} 1.0' in text
    assert "chat_latency_seconds_count 1" in text
    assert 'chat_latency_seconds{quantile="0.5"} 0.5' in text


def test_reset_clears_state() -> None:
    metrics = get_metrics()
    metrics.increment("x_total")
    reset_metrics()
    assert metrics.counter_value("x_total") == 0.0
