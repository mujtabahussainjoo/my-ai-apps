"""Token and cost tracking for LLM calls (TASK-015).

Every successful non-streaming result and every terminal streaming chunk carries a
:class:`~ecommerce_support.llm.types.Usage`. :class:`UsageTracker` accumulates those into
per-model totals and estimates USD cost from a static price table. Token counts are exact
(provider-reported); **cost figures are estimates** from public list prices that go stale — they
are for observability, not billing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from threading import Lock

from pydantic import BaseModel, ConfigDict, Field

from ecommerce_support.llm.types import Usage

# Public list prices in USD per 1,000,000 tokens as (input, output). Estimates only.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-opus-4-1": (15.0, 75.0),
    "gpt-4o": (2.5, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.40, 1.60),
    "gemini-1.5-pro": (1.25, 5.0),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.0),
    "text-embedding-3-small": (0.02, 0.0),
}


def price_for(model: str) -> tuple[float, float] | None:
    """Return ``(input, output)`` USD per 1M tokens for ``model``, or ``None`` if unknown.

    Matches exact names first, then the longest known prefix so dated snapshots such as
    ``claude-sonnet-4-5-20250929`` resolve to ``claude-sonnet-4-5``.
    """
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    candidates = [key for key in MODEL_PRICING if model.startswith(key)]
    if not candidates:
        return None
    return MODEL_PRICING[max(candidates, key=len)]


def estimate_cost(model: str, usage: Usage) -> float:
    """Estimated USD cost for ``usage`` on ``model`` (0.0 when the model is unpriced)."""
    price = price_for(model)
    if price is None:
        return 0.0
    input_price, output_price = price
    return (usage.prompt_tokens * input_price + usage.completion_tokens * output_price) / 1_000_000


class UsageRecord(BaseModel):
    """One tracked call's token usage and estimated cost."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0.0)
    recorded_at: datetime


class UsageTotals(BaseModel):
    """Aggregated usage over a set of records."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    calls: int = Field(ge=0)
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0.0)


class UsageTracker:
    """Thread-safe in-memory accumulator of :class:`UsageRecord` entries."""

    def __init__(self) -> None:
        self._records: list[UsageRecord] = []
        self._lock = Lock()

    def record(self, *, provider: str, model: str, usage: Usage) -> UsageRecord:
        """Append a record for one completed call and return it."""
        entry = UsageRecord(
            provider=provider,
            model=model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            cost_usd=estimate_cost(model, usage),
            recorded_at=datetime.now(UTC),
        )
        with self._lock:
            self._records.append(entry)
        return entry

    def records(self) -> list[UsageRecord]:
        """Return a snapshot copy of recorded entries."""
        with self._lock:
            return list(self._records)

    def totals(self, *, model: str | None = None) -> UsageTotals:
        """Aggregate tokens/cost, optionally restricted to one ``model``."""
        with self._lock:
            selected = [r for r in self._records if model is None or r.model == model]
        return UsageTotals(
            calls=len(selected),
            prompt_tokens=sum(r.prompt_tokens for r in selected),
            completion_tokens=sum(r.completion_tokens for r in selected),
            total_tokens=sum(r.total_tokens for r in selected),
            cost_usd=sum(r.cost_usd for r in selected),
        )

    def reset(self) -> None:
        """Drop all records (used by tests and per-request scoping)."""
        with self._lock:
            self._records.clear()


_tracker = UsageTracker()


def get_usage_tracker() -> UsageTracker:
    """Return the process-wide default tracker."""
    return _tracker


def reset_usage_tracker() -> None:
    """Clear the process-wide default tracker."""
    _tracker.reset()
