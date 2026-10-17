"""LLM capability declarations and enforcement.

Every capability a caller relies on (streaming, structured output, tool calling) is a named
:class:`LLMCapability`. Clients declare the set they support; requesting an unsupported one
fails loudly with :class:`~ecommerce_support.core.exceptions.LLMCapabilityError` rather than
silently degrading (NFR-007 / AGENTS.md).
"""

from __future__ import annotations

from collections.abc import Set
from enum import StrEnum

from ecommerce_support.core.exceptions import LLMCapabilityError


class LLMCapability(StrEnum):
    """Capabilities a provider/model may or may not support."""

    complete = "complete"
    stream = "stream"
    structured = "structured"
    tool_calling = "tool_calling"
    vision = "vision"


def ensure_capability(
    supported: Set[LLMCapability],
    required: LLMCapability,
    *,
    provider: str,
) -> None:
    """Raise :class:`LLMCapabilityError` when ``required`` is not in ``supported``."""
    if required not in supported:
        raise LLMCapabilityError(
            f"LLM provider {provider!r} does not support the {required.value!r} capability.",
            details={"provider": provider, "capability": required.value},
        )
