"""Heuristic prompt-injection detection for untrusted text (FR-032).

Retrieved policy documents and incoming customer messages are untrusted input. This module scores
text against weighted patterns for instruction-override, prompt/secret exfiltration, and role
spoofing. It is deliberately deterministic and offline so it is testable and safe to run at both
ingest and answer time. It is a defense-in-depth signal, not the security boundary: the grounded
generator additionally delimits evidence and drops anything above the score threshold.
"""

from __future__ import annotations

import re

from ecommerce_support.schemas.guardrails import InjectionAssessment

__all__ = [
    "DEFAULT_THRESHOLD",
    "assess_prompt_injection",
    "is_prompt_injection",
]

DEFAULT_THRESHOLD = 0.7

_PATTERNS: tuple[tuple[str, re.Pattern[str], float], ...] = (
    (
        "ignore_instructions",
        re.compile(
            r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}"
            r"\b(previous|prior|above|earlier|all|any)\b[^.\n]{0,20}"
            r"\b(instruction|prompt|rule|direction|message|context)s?\b",
            re.IGNORECASE,
        ),
        1.0,
    ),
    (
        "reveal_system_prompt",
        re.compile(
            r"\b(reveal|show|print|repeat|expose|disclose|output)\b[^.\n]{0,30}"
            r"\b(system|developer|hidden|secret|initial|original)\b[^.\n]{0,20}"
            r"\b(prompt|instruction|message|rule)s?\b",
            re.IGNORECASE,
        ),
        1.0,
    ),
    (
        "jailbreak",
        re.compile(
            r"\b(jailbreak|developer mode|dan mode|do anything now|sudo mode)\b", re.IGNORECASE
        ),
        1.0,
    ),
    (
        "role_spoof",
        re.compile(r"^\s*(system|assistant)\s*:", re.IGNORECASE | re.MULTILINE),
        0.7,
    ),
    (
        "role_override",
        re.compile(
            r"\b(you are now|act as|pretend to be|from now on,? you|new instructions)\b",
            re.IGNORECASE,
        ),
        0.7,
    ),
    (
        "secret_exfiltration",
        re.compile(
            r"\b(api[ _-]?key|password|passphrase|credential|secret token|access token)s?\b",
            re.IGNORECASE,
        ),
        0.5,
    ),
    (
        "delimiter_escape",
        re.compile(
            r"</?(system|instructions?|policy|evidence)>|^\s*```", re.IGNORECASE | re.MULTILINE
        ),
        0.4,
    ),
)


def assess_prompt_injection(
    text: str, *, threshold: float = DEFAULT_THRESHOLD
) -> InjectionAssessment:
    """Score ``text`` for injection patterns and flag it when the score reaches ``threshold``."""
    matches = [name for name, pattern, _ in _PATTERNS if pattern.search(text or "")]
    weights = {name: weight for name, _, weight in _PATTERNS}
    score = min(1.0, sum(weights[name] for name in matches))
    return InjectionAssessment(score=score, flagged=score >= threshold, matches=matches)


def is_prompt_injection(text: str, *, threshold: float = DEFAULT_THRESHOLD) -> bool:
    """Convenience predicate: True when ``text`` looks like a prompt-injection attempt."""
    return assess_prompt_injection(text, threshold=threshold).flagged
