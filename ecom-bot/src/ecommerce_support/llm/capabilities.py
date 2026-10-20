"""LLM capability declarations, the per-provider matrix, and enforcement.

Every capability a caller relies on (streaming, structured output, tool calling) is a named
:class:`LLMCapability`. Each provider declares the set it supports in :data:`PROVIDER_CAPABILITIES`;
requesting an unsupported one fails loudly with
:class:`~ecommerce_support.core.exceptions.LLMCapabilityError` rather than silently degrading
(NFR-007 / AGENTS.md).

The matrix is the single source of truth: adapters read their ``capabilities`` from
:func:`capabilities_for` so provider behavior cannot drift. Providers are enabled one at a time
via ``config/llm.yaml`` / ``LLM__PROVIDER`` (ACC-009); the matrix documents what each supports.
"""

from __future__ import annotations

from collections.abc import Set
from enum import StrEnum

from ecommerce_support.core.exceptions import ConfigurationError, LLMCapabilityError


class LLMCapability(StrEnum):
    """Capabilities a provider/model may or may not support."""

    complete = "complete"
    stream = "stream"
    structured = "structured"
    tool_calling = "tool_calling"
    vision = "vision"


PROVIDER_CAPABILITIES: dict[str, frozenset[LLMCapability]] = {
    "mock": frozenset(
        {
            LLMCapability.complete,
            LLMCapability.stream,
            LLMCapability.structured,
            LLMCapability.tool_calling,
        }
    ),
    "anthropic": frozenset(
        {
            LLMCapability.complete,
            LLMCapability.stream,
            LLMCapability.structured,
            LLMCapability.tool_calling,
        }
    ),
    "openai": frozenset(
        {
            LLMCapability.complete,
            LLMCapability.stream,
            LLMCapability.structured,
            LLMCapability.tool_calling,
        }
    ),
    "gemini": frozenset(
        {
            LLMCapability.complete,
            LLMCapability.stream,
            LLMCapability.structured,
            LLMCapability.tool_calling,
        }
    ),
    "ollama": frozenset(
        {
            LLMCapability.complete,
            LLMCapability.stream,
            LLMCapability.tool_calling,
        }
    ),
    "openai_compatible": frozenset(
        {
            LLMCapability.complete,
            LLMCapability.stream,
            LLMCapability.tool_calling,
        }
    ),
}


def capabilities_for(provider: str) -> frozenset[LLMCapability]:
    """Return the declared capabilities for ``provider`` (fails loudly if unknown)."""
    try:
        return PROVIDER_CAPABILITIES[provider]
    except KeyError:
        raise ConfigurationError(
            f"No capability matrix entry for LLM provider {provider!r}.",
            details={"provider": provider},
        ) from None


def unsupported(provider: str, capability: LLMCapability) -> bool:
    """True when ``provider`` does not declare ``capability``."""
    return capability not in capabilities_for(provider)


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
