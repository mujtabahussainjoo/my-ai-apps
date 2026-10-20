"""Operational metrics endpoint (FR-055).

Exposes the process-wide counters/histograms plus LLM token usage and estimated cost from the
usage tracker. Values are numeric aggregates only — no prompts, secrets, or customer text
(FR-056). The endpoint mirrors the health probes: unauthenticated, read-only, and cheap.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from ecommerce_support.core.metrics import (
    COUNTER_LLM_COST_MICROS,
    COUNTER_LLM_TOKENS,
    get_metrics,
    render_prometheus,
)
from ecommerce_support.llm.usage import get_usage_tracker

router = APIRouter(tags=["observability"])


def render_metrics() -> str:
    """Render counters, histograms, and LLM usage in Prometheus text exposition format."""
    lines = render_prometheus(get_metrics()).rstrip("\n").split("\n")
    lines.extend(_usage_lines())
    return "\n".join(line for line in lines if line) + "\n"


def _usage_lines() -> list[str]:
    totals: dict[str, dict[str, float]] = {}
    for record in get_usage_tracker().records():
        bucket = totals.setdefault(
            record.model, {"prompt": 0.0, "completion": 0.0, "cost_micros": 0.0}
        )
        bucket["prompt"] += record.prompt_tokens
        bucket["completion"] += record.completion_tokens
        bucket["cost_micros"] += round(record.cost_usd * 1_000_000, 6)
    lines: list[str] = []
    for model, bucket in sorted(totals.items()):
        lines.append(f'{COUNTER_LLM_TOKENS}{{model="{model}",kind="prompt"}} {bucket["prompt"]}')
        lines.append(
            f'{COUNTER_LLM_TOKENS}{{model="{model}",kind="completion"}} {bucket["completion"]}'
        )
        lines.append(f'{COUNTER_LLM_COST_MICROS}{{model="{model}"}} {bucket["cost_micros"]}')
    return lines


@router.get("/metrics", summary="Operational metrics (Prometheus text format)")
async def metrics() -> PlainTextResponse:
    """Render counters, histograms, and LLM usage in Prometheus text exposition format."""
    return PlainTextResponse(
        render_metrics(), media_type="text/plain; version=0.0.4; charset=utf-8"
    )
