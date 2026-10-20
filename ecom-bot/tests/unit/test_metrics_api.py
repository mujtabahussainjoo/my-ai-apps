"""Tests for the /metrics endpoint and LLM usage export (FR-055)."""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from ecommerce_support.core.metrics import get_metrics, reset_metrics
from ecommerce_support.llm.types import Usage
from ecommerce_support.llm.usage import get_usage_tracker, reset_usage_tracker
from ecommerce_support.main import create_app


async def test_metrics_endpoint_renders_counters(client: AsyncClient) -> None:
    reset_metrics()
    get_metrics().increment("tool_calls_total", tool="get_order", status="ok")
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert 'tool_calls_total{status="ok",tool="get_order"} 1.0' in response.text
    reset_metrics()


async def test_metrics_endpoint_includes_llm_usage() -> None:
    reset_usage_tracker()
    get_usage_tracker().record(
        provider="mock",
        model="gpt-4o-mini",
        usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        response = await http_client.get("/metrics")
    assert 'llm_tokens_total{model="gpt-4o-mini",kind="prompt"} 10' in response.text
    assert 'llm_tokens_total{model="gpt-4o-mini",kind="completion"} 5' in response.text
    assert 'llm_cost_micros_total{model="gpt-4o-mini"}' in response.text
    reset_usage_tracker()
