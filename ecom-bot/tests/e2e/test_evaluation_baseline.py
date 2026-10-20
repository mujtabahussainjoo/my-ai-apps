"""End-to-end evaluation baseline + metrics wiring (FR-055)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ecommerce_support.core.metrics import get_metrics, reset_metrics
from ecommerce_support.evaluation.routing import RoutingEvaluator, load_routing_dataset
from ecommerce_support.schemas import ChatRequest

pytestmark = pytest.mark.e2e

_SENSITIVE = "ada@example.com 4111 1111 1111 1111"


async def test_bundled_routing_dataset_matches_real_graph(e2e_stack: Any) -> None:
    dataset = load_routing_dataset()
    report = await RoutingEvaluator(e2e_stack.graph).evaluate(dataset)
    assert report.case_count == len(dataset.cases)
    assert report.routing_accuracy == 1.0
    assert report.tool_selection_accuracy == 1.0


async def test_chat_turn_records_metrics(e2e_stack: Any) -> None:
    reset_metrics()
    await e2e_stack.chat.chat(ChatRequest(message="Where is my order ord-1?"), user_id="cust-1")
    metrics = get_metrics()
    assert metrics.counter_value("chat_turns_total", outcome="answered") == 1
    assert metrics.histogram_samples("chat_latency_seconds")
    assert metrics.counter_value("tool_calls_total", tool="get_order", status="ok") == 1


async def test_streaming_turn_records_metrics(e2e_stack: Any) -> None:
    reset_metrics()
    async for _event in e2e_stack.chat.stream(
        ChatRequest(message="Where is my order ord-1?"), user_id="cust-1"
    ):
        pass
    metrics = get_metrics()
    assert metrics.counter_value("chat_turns_total", outcome="answered") == 1
    assert metrics.histogram_samples("chat_latency_seconds")


async def test_metrics_exclude_customer_text_and_pii(e2e_stack: Any) -> None:
    reset_metrics()
    await e2e_stack.chat.chat(
        ChatRequest(message=f"Where is my order ord-1? contact {_SENSITIVE}"),
        user_id="cust-1",
    )
    snapshot = json.dumps(get_metrics().snapshot())
    assert "ada@example.com" not in snapshot
    assert "4111 1111 1111 1111" not in snapshot
    assert "ord-1" not in snapshot
