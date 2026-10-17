"""The provider-independent LLM client interface (NFR-007, ACC-009).

Agents and tools depend only on :class:`LLMClient` obtained from ``llm.factory``; they never
import a provider SDK. Providers implement this ABC under ``llm/providers/``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import ClassVar, TypeVar

from pydantic import BaseModel

from ecommerce_support.llm.capabilities import LLMCapability, ensure_capability
from ecommerce_support.llm.types import (
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
    ToolDefinition,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMClient(ABC):
    """Common interface every LLM provider adapter implements.

    Subclasses declare ``provider`` (a stable identifier) and ``capabilities`` (the set of
    :class:`LLMCapability` they support). Callers should guard optional behavior with
    :meth:`require` so unsupported requests fail loudly at call time.
    """

    provider: ClassVar[str] = "unknown"
    capabilities: ClassVar[frozenset[LLMCapability]] = frozenset()

    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier this client is configured to use."""
        raise NotImplementedError

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Run a single, non-streamed generation."""
        raise NotImplementedError

    @abstractmethod
    def astream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        """Stream a generation as an async iterator of :class:`StreamChunk`."""
        raise NotImplementedError

    @abstractmethod
    async def structured(
        self,
        request: CompletionRequest,
        schema: type[ModelT],
    ) -> ModelT:
        """Generate output validated against ``schema`` and return the parsed instance."""
        raise NotImplementedError

    @abstractmethod
    async def tool_call(
        self,
        request: CompletionRequest,
        tools: Sequence[ToolDefinition],
        *,
        tool_choice: str | None = None,
    ) -> CompletionResponse:
        """Run a generation that may request one or more tool invocations."""
        raise NotImplementedError

    def supports(self, capability: LLMCapability) -> bool:
        """True when this client advertises ``capability``."""
        return capability in self.capabilities

    def require(self, capability: LLMCapability) -> None:
        """Raise :class:`LLMCapabilityError` when ``capability`` is unsupported."""
        ensure_capability(self.capabilities, capability, provider=self.provider)

    async def aclose(self) -> None:
        """Release provider resources. Providers may override; default is a no-op."""
        return None
