"""Provider-independent LLM layer (NFR-007).

Public surface: the :class:`LLMClient` interface, capability declarations, and the shared
data contracts. Provider adapters live in :mod:`ecommerce_support.llm.providers`.
"""

from __future__ import annotations

from ecommerce_support.llm.base import LLMClient
from ecommerce_support.llm.capabilities import LLMCapability, ensure_capability
from ecommerce_support.llm.factory import create_llm_client, get_llm_client
from ecommerce_support.llm.retry import RetryingLLMClient, RetryPolicy
from ecommerce_support.llm.types import (
    ChatMessage,
    CompletionRequest,
    CompletionResponse,
    Role,
    StreamChunk,
    ToolCall,
    ToolCallResult,
    ToolDefinition,
    Usage,
)
from ecommerce_support.llm.usage import (
    UsageRecord,
    UsageTotals,
    UsageTracker,
    estimate_cost,
    get_usage_tracker,
    reset_usage_tracker,
)

__all__ = [
    "ChatMessage",
    "CompletionRequest",
    "CompletionResponse",
    "LLMCapability",
    "LLMClient",
    "RetryPolicy",
    "RetryingLLMClient",
    "Role",
    "StreamChunk",
    "ToolCall",
    "ToolCallResult",
    "ToolDefinition",
    "Usage",
    "UsageRecord",
    "UsageTotals",
    "UsageTracker",
    "create_llm_client",
    "ensure_capability",
    "estimate_cost",
    "get_llm_client",
    "get_usage_tracker",
    "reset_usage_tracker",
]
