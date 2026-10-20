"""Metrics must stay low-cardinality and free of customer text/PII (FR-056, SEC-005)."""

from __future__ import annotations

import pytest

from ecommerce_support.core.metrics import get_metrics, reset_metrics

pytestmark = pytest.mark.security

_ALLOWED_LABELS = {"tool", "status", "outcome", "rating", "model", "kind", "result", "agent"}


def test_metric_label_keys_are_allowlisted() -> None:
    reset_metrics()
    metrics = get_metrics()
    metrics.increment("tool_calls_total", tool="get_order", status="ok")
    metrics.increment("chat_turns_total", outcome="answered")
    metrics.increment("escalations_total", result="created")
    for counter in metrics.snapshot()["counters"]:
        assert set(counter["labels"]) <= _ALLOWED_LABELS


def test_no_pii_is_accepted_as_labels_by_construction() -> None:
    reset_metrics()
    metrics = get_metrics()
    metrics.increment("tool_calls_total", tool="get_order", status="ok")
    snapshot = str(metrics.snapshot())
    assert "ada@example.com" not in snapshot
    assert "4111 1111 1111 1111" not in snapshot
