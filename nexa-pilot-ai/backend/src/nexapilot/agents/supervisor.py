"""Supervisor routing.

Classification is deterministic and rule-based so that routing is predictable and
testable, and so that security-sensitive decisions never depend on model output.
The optional model-assisted tie-break is only used when the rules are ambiguous
*and* the active provider supports structured output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from nexapilot.agents.state import ALL_WORKFLOWS

#: Keyword -> workflow. Matching is case-insensitive on word boundaries.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "research": (
        "search",
        "search for",
        "look up",
        "find out",
        "latest",
        "news",
        "recent news",
        "who is",
        "what is",
        "explain",
        "research",
        "compare",
        "documentation",
        "docs",
        "release notes",
        "changelog",
        "papers",
        "wikipedia",
        "how does",
        "why did",
        "summarize",
        "summarise",
        "review articles",
    ),
    "travel": (
        "flight",
        "flights",
        "hotel",
        "hotels",
        "train",
        "trains",
        "booking",
        "book a",
        "book me",
        "ticket",
        "tickets",
        "trip",
        "travel",
        "vacation",
        "holiday",
        "stay",
        "airfare",
        "itinerary",
        "airport",
        "check-in",
        "boarding",
        "hostel",
        "resort",
        "airbnb",
    ),
    "email": (
        "email",
        "e-mail",
        "mail",
        "inbox",
        "unread",
        "draft",
        "reply to",
        "reply",
        "forward",
        "cc ",
        "bcc",
        "newsletter",
        "sender",
        "subject line",
        "gmail",
        "outlook",
        "imap",
    ),
    "calendar": (
        "calendar",
        "schedule",
        "scheduling",
        "meeting",
        "meetings",
        "appointment",
        "appointments",
        "event",
        "events",
        "reminder",
        "remind me",
        "availability",
        "free slot",
        "reschedule",
        "timezone",
        "time zone",
        "agenda",
    ),
    "finance": (
        "stock",
        "stocks",
        "share",
        "shares",
        "ticker",
        "portfolio",
        "etf",
        "mutual fund",
        "index fund",
        "crypto",
        "bitcoin",
        "ethereum",
        "dividend",
        "invest",
        "investment",
        "market cap",
        "pe ratio",
        "price",
        "quote",
        "market",
        "balance",
        "position",
        "order",
        "buy",
        "sell",
        "nasdaq",
        "nyse",
        "sensex",
        "nifty",
        "valuation",
    ),
    "coding": (
        "code",
        "coding",
        "function",
        "class",
        "bug",
        "debug",
        "refactor",
        "test",
        "tests",
        "pytest",
        "repo",
        "repository",
        "project",
        "compile",
        "typecheck",
        "type check",
        "lint",
        "ruff",
        "mypy",
        "python",
        "javascript",
        "typescript",
        "rust",
        "golang",
        "java",
        "react",
        "implement",
        "script",
        "shell",
        "command",
        "unit test",
        "stack trace",
        "exception",
    ),
}


@dataclass
class RouteDecision:
    workflow: str
    confidence: float = 0.0
    reason: str = ""
    matched: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "workflow": self.workflow,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "matched": self.matched,
            "alternatives": self.alternatives,
        }


#: Interrogative phrases are weak evidence: they appear in every domain.
GENERIC_RESEARCH_PHRASES = frozenset(
    {"what is", "who is", "how does", "why did", "explain", "compare"}
)


@lru_cache(maxsize=1)
def _compiled_keywords() -> dict[str, list[tuple[str, int, re.Pattern[str]]]]:
    """Pre-compile word-boundary patterns.

    Substring counting is wrong: ``"latest"`` would otherwise match the coding
    keyword ``"test"``. Domain keywords weigh more than generic interrogatives,
    and multi-word phrases weigh the most because they are strong evidence.
    """
    compiled: dict[str, list[tuple[str, int, re.Pattern[str]]]] = {}
    for workflow, keywords in KEYWORDS.items():
        entries: list[tuple[str, int, re.Pattern[str]]] = []
        for keyword in keywords:
            phrase = keyword.strip()
            if not phrase:
                continue
            if phrase in GENERIC_RESEARCH_PHRASES:
                weight = 1
            elif " " in phrase:
                weight = 3
            else:
                weight = 2
            pattern = re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)", re.IGNORECASE)
            entries.append((phrase, weight, pattern))
        compiled[workflow] = entries
    return compiled


def _score(text: str) -> dict[str, tuple[int, list[str]]]:
    scores: dict[str, tuple[int, list[str]]] = {}
    for workflow, entries in _compiled_keywords().items():
        hits: list[str] = []
        count = 0
        for phrase, weight, pattern in entries:
            occurrences = len(pattern.findall(text))
            if occurrences == 0:
                continue
            count += occurrences * weight
            hits.append(phrase)
        if count:
            scores[workflow] = (count, hits)
    return scores


def classify_request(text: str) -> RouteDecision:
    """Pick the single workflow most likely to satisfy the request."""
    stripped = text.strip()
    if not stripped:
        return RouteDecision(workflow="general", confidence=0.0, reason="empty request")

    scores = _score(stripped)
    if not scores:
        return RouteDecision(
            workflow="general",
            confidence=0.2,
            reason="no workflow-specific keywords found",
        )

    ranked = sorted(scores.items(), key=lambda item: (-item[1][0], item[0]))
    (top_workflow, (top_count, top_hits)) = ranked[0]
    runner_up = ranked[1][1][0] if len(ranked) > 1 else 0

    if top_count == 1 and runner_up == 0:
        # A single keyword mention is weak evidence.
        return RouteDecision(
            workflow=top_workflow,
            confidence=0.45,
            reason=f"matched {top_hits[0]!r}",
            matched=top_hits,
        )

    confidence = min(0.95, 0.4 + 0.12 * top_count + (0.1 if top_count > runner_up else 0.0))
    return RouteDecision(
        workflow=top_workflow,
        confidence=confidence,
        reason=f"keyword scores: {top_hits}",
        matched=top_hits,
        alternatives=[workflow for workflow, _ in ranked[1:3]],
    )


def validate_workflow(workflow: str) -> str:
    return workflow if workflow in ALL_WORKFLOWS else "general"
