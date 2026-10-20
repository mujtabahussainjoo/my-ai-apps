"""Lightweight, framework-free metrics registry (FR-055).

A process-wide registry of counters and histograms used to record baseline operational
metrics (latency, LLM token usage/cost, tool selection, resolution rate, escalation success,
ticket duplication, feedback rating). It intentionally avoids a heavyweight dependency: values
are exposed as a JSON ``snapshot`` for the ``/metrics`` endpoint and as Prometheus text.

Metric names and label sets are deliberately small and low-cardinality. No PII, prompts, or
secrets are ever recorded here (FR-056) — only numeric aggregates keyed by stable labels.
"""

from __future__ import annotations

from threading import Lock
from typing import Any

COUNTER_CHAT_TURNS = "chat_turns_total"
COUNTER_LLM_TOKENS = "llm_tokens_total"
COUNTER_LLM_COST_MICROS = "llm_cost_micros_total"
COUNTER_TOOL_CALLS = "tool_calls_total"
COUNTER_ESCALATIONS = "escalations_total"
COUNTER_FEEDBACK = "feedback_total"
HISTOGRAM_CHAT_LATENCY = "chat_latency_seconds"
HISTOGRAM_FEEDBACK_RATING = "feedback_rating"

LabelSet = tuple[tuple[str, str], ...]
HistogramKey = tuple[str, LabelSet]


def _label_key(labels: dict[str, str]) -> LabelSet:
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def _quantile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = quantile * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    fraction = position - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


class Metrics:
    """Thread-safe accumulator of counters and histograms."""

    def __init__(self) -> None:
        self._counters: dict[tuple[str, LabelSet], float] = {}
        self._histograms: dict[HistogramKey, list[float]] = {}
        self._lock = Lock()

    def increment(self, name: str, value: float = 1.0, **labels: str) -> None:
        """Add ``value`` (default 1) to counter ``name`` for the given labels."""
        key = (name, _label_key(labels))
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value

    def observe(self, name: str, value: float, **labels: str) -> None:
        """Record one observation for histogram ``name``."""
        key = (name, _label_key(labels))
        with self._lock:
            self._histograms.setdefault(key, []).append(value)

    def reset(self) -> None:
        """Clear all counters and histograms (tests only)."""
        with self._lock:
            self._counters.clear()
            self._histograms.clear()

    def counter_value(self, name: str, **labels: str) -> float:
        """Return the current value of a counter (0.0 when unset)."""
        with self._lock:
            return self._counters.get((name, _label_key(labels)), 0.0)

    def histogram_samples(self, name: str) -> list[float]:
        """Return a flat copy of every sample recorded for ``name`` across all labels."""
        with self._lock:
            return [
                value
                for (metric, _labels), values in self._histograms.items()
                if metric == name
                for value in values
            ]

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable view of all metrics."""
        with self._lock:
            counters: list[dict[str, Any]] = [
                {"name": name, "labels": dict(labels), "value": value}
                for (name, labels), value in self._counters.items()
            ]
            histograms: list[dict[str, Any]] = [
                {
                    "name": name,
                    "labels": dict(labels),
                    "count": len(values),
                    "sum": round(sum(values), 6),
                    "min": round(min(values), 6),
                    "max": round(max(values), 6),
                    "p50": round(_quantile(values, 0.5), 6),
                    "p95": round(_quantile(values, 0.95), 6),
                }
                for (name, labels), values in self._histograms.items()
            ]
        counters.sort(key=lambda item: (item["name"], tuple(sorted(item["labels"].items()))))
        histograms.sort(key=lambda item: (item["name"], tuple(sorted(item["labels"].items()))))
        return {"counters": counters, "histograms": histograms}


def _format_labels(labels: LabelSet) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{key}="{_escape(value)}"' for key, value in labels)
    return "{" + inner + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def render_prometheus(metrics: Metrics) -> str:
    """Render counters and histograms in Prometheus text exposition format."""
    snapshot = metrics.snapshot()
    lines: list[str] = []
    for counter in snapshot["counters"]:
        labels = _format_labels(tuple(sorted(counter["labels"].items())))
        lines.append(f"{counter['name']}{labels} {counter['value']}")
    for histogram in snapshot["histograms"]:
        base_labels = tuple(sorted(histogram["labels"].items()))
        suffix = ", " if base_labels else ""
        lines.append(f"{histogram['name']}_count{_format_labels(base_labels)} {histogram['count']}")
        lines.append(f"{histogram['name']}_sum{_format_labels(base_labels)} {histogram['sum']}")
        lines.append(f'{histogram["name"]}{{{suffix}quantile="0.5"}} {histogram["p50"]}')
        lines.append(f'{histogram["name"]}{{{suffix}quantile="0.95"}} {histogram["p95"]}')
    return "\n".join(lines) + "\n"


_metrics = Metrics()


def get_metrics() -> Metrics:
    """Return the process-wide metrics registry."""
    return _metrics


def reset_metrics() -> None:
    """Clear the process-wide registry (tests only)."""
    _metrics.reset()


def record_chat_turn(outcome: str, latency_seconds: float) -> None:
    """Record one completed chat turn: outcome counter + latency histogram (FR-055)."""
    metrics = get_metrics()
    metrics.increment(COUNTER_CHAT_TURNS, outcome=outcome)
    metrics.observe(HISTOGRAM_CHAT_LATENCY, latency_seconds)


__all__ = [
    "COUNTER_CHAT_TURNS",
    "COUNTER_ESCALATIONS",
    "COUNTER_FEEDBACK",
    "COUNTER_LLM_COST_MICROS",
    "COUNTER_LLM_TOKENS",
    "COUNTER_TOOL_CALLS",
    "HISTOGRAM_CHAT_LATENCY",
    "HISTOGRAM_FEEDBACK_RATING",
    "Metrics",
    "get_metrics",
    "record_chat_turn",
    "render_prometheus",
    "reset_metrics",
]
