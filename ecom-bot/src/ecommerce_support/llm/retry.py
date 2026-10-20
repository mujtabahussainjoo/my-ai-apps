"""Bounded retries, per-call timeouts, and the retrying client wrapper (TASK-015).

Policy (IMPLEMENTATION_PLAN §4, agent-development skill): at most 3 attempts, exponential
backoff with jitter, retry **only** transient failures (timeout / 429 / 5xx / unreachable).
Auth, capability, and validation failures are never retried. Non-``LLMError`` exceptions
(programmer errors such as ``ValueError``) always propagate immediately — only provider
failures that the adapters normalized into :class:`~ecommerce_support.core.exceptions.LLMError`
are eligible for retry.

Streaming is deliberately **not** retried: a partially-consumed stream cannot be replayed
safely, so ``astream`` is passed through to the underlying provider. Per-call timeouts apply
to non-streaming calls only.

The retry engine here is the single place retry policy lives; adapters keep ``max_retries=0``
on their SDK clients so the SDK never double-retries.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence

from pydantic import BaseModel, ConfigDict, Field

from ecommerce_support.core.config import LLMConfig
from ecommerce_support.core.exceptions import (
    LLMAuthError,
    LLMCapabilityError,
    LLMError,
    LLMTimeoutError,
)
from ecommerce_support.llm.base import LLMClient, ModelT
from ecommerce_support.llm.capabilities import LLMCapability
from ecommerce_support.llm.types import (
    CompletionRequest,
    CompletionResponse,
    StreamChunk,
    ToolDefinition,
)
from ecommerce_support.llm.usage import UsageTracker

SleepFn = Callable[[float], Awaitable[None]]
RngFn = Callable[[], float]


class RetryPolicy(BaseModel):
    """Immutable retry configuration. ``max_attempts`` is the total attempt budget."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_attempts: int = Field(default=3, ge=1, le=10)
    base_seconds: float = Field(default=0.5, gt=0)
    max_seconds: float = Field(default=8.0, gt=0)
    jitter: float = Field(default=0.5, ge=0.0, le=1.0)

    @classmethod
    def from_config(cls, config: LLMConfig) -> RetryPolicy:
        """Build a policy from :class:`LLMConfig` (``max_retries`` = total attempts)."""
        return cls(
            max_attempts=max(1, config.max_retries),
            base_seconds=config.retry_backoff_base_seconds,
            max_seconds=config.retry_backoff_max_seconds,
        )


def is_retryable(error: LLMError) -> bool:
    """True when ``error`` is a transient provider failure worth retrying.

    Auth and capability failures are never retryable even if a subclass mislabels them.
    """
    if isinstance(error, (LLMAuthError, LLMCapabilityError)):
        return False
    return error.retryable


def backoff_delay(attempt: int, policy: RetryPolicy, *, rng: RngFn = random.random) -> float:
    """Delay in seconds before retry ``attempt + 1`` (``attempt`` is 1-based).

    ``base * 2**(attempt-1)``, scaled by ``1 ± jitter``, capped at ``max_seconds``.
    """
    base: float = policy.base_seconds * (2 ** (attempt - 1))
    jitter: float = policy.jitter
    factor: float = 1.0 - jitter + (2.0 * jitter * rng())
    delay: float = min(base * factor, policy.max_seconds)
    return delay


async def with_retries[T](
    operation: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy,
    sleep: SleepFn = asyncio.sleep,
    rng: RngFn = random.random,
    on_retry: Callable[[int, float, LLMError], None] | None = None,
) -> T:
    """Run ``operation`` with the bounded retry policy and return its result.

    Raises the last :class:`LLMError` when the budget is exhausted, or immediately for
    non-retryable errors and non-``LLMError`` exceptions.
    """
    last_error: LLMError | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return await operation()
        except LLMError as exc:
            last_error = exc
            if not is_retryable(exc) or attempt >= policy.max_attempts:
                raise
            delay = backoff_delay(attempt, policy, rng=rng)
            if on_retry is not None:
                on_retry(attempt, delay, exc)
            await sleep(delay)
    if last_error is not None:
        raise last_error
    raise RuntimeError("with_retries exhausted without an error")  # pragma: no cover


class RetryingLLMClient(LLMClient):
    """Decorator that adds per-call timeouts, bounded retries, and usage tracking.

    Wraps any provider adapter. ``supports``/``require``/``model_name`` delegate to the inner
    client so capability behavior is unchanged. Streaming passes through without retry or
    timeout (see module docstring); usage from the terminal chunk is still recorded.
    """

    provider = "retrying"

    def __init__(
        self,
        inner: LLMClient,
        policy: RetryPolicy,
        *,
        timeout_seconds: float = 60.0,
        tracker: UsageTracker | None = None,
        sleep: SleepFn = asyncio.sleep,
        rng: RngFn = random.random,
    ) -> None:
        self._inner = inner
        self._policy = policy
        self._timeout_seconds = timeout_seconds
        self._tracker = tracker
        self._sleep = sleep
        self._rng = rng

    def unwrap(self) -> LLMClient:
        """Return the underlying provider adapter."""
        return self._inner

    def model_name(self) -> str:
        return self._inner.model_name()

    def supports(self, capability: LLMCapability) -> bool:
        return self._inner.supports(capability)

    def require(self, capability: LLMCapability) -> None:
        self._inner.require(capability)

    async def _run[T](self, operation: Callable[[], Awaitable[T]]) -> T:
        async def attempt() -> T:
            try:
                async with asyncio.timeout(self._timeout_seconds):
                    return await operation()
            except TimeoutError as exc:
                raise LLMTimeoutError(
                    f"LLM provider call timed out after {self._timeout_seconds:g}s.",
                    details={
                        "provider": self._inner.provider,
                        "model": self._inner.model_name(),
                        "timeout_seconds": self._timeout_seconds,
                    },
                ) from exc

        return await with_retries(attempt, policy=self._policy, sleep=self._sleep, rng=self._rng)

    def _record(self, response: CompletionResponse) -> None:
        if self._tracker is None:
            return
        self._tracker.record(
            provider=self._inner.provider,
            model=self._inner.model_name(),
            usage=response.usage,
        )

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        response = await self._run(lambda: self._inner.complete(request))
        self._record(response)
        return response

    async def tool_call(
        self,
        request: CompletionRequest,
        tools: Sequence[ToolDefinition],
        *,
        tool_choice: str | None = None,
    ) -> CompletionResponse:
        response = await self._run(
            lambda: self._inner.tool_call(request, tools, tool_choice=tool_choice)
        )
        self._record(response)
        return response

    async def structured(
        self,
        request: CompletionRequest,
        schema: type[ModelT],
    ) -> ModelT:
        # The structured() contract returns the parsed model only (no Usage), so there is
        # nothing to record here; callers that need usage should use complete()/tool_call().
        return await self._run(lambda: self._inner.structured(request, schema))

    async def astream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        # No retry: a partially-consumed stream cannot be replayed. Usage from the terminal
        # chunk is still recorded for tracking.
        async for chunk in self._inner.astream(request):
            if chunk.done and chunk.usage is not None and self._tracker is not None:
                self._tracker.record(
                    provider=self._inner.provider,
                    model=self._inner.model_name(),
                    usage=chunk.usage,
                )
            yield chunk

    async def aclose(self) -> None:
        await self._inner.aclose()
