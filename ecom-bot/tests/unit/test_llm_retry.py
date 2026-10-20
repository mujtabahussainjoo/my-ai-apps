"""Retry, timeout, and failure-injection tests for the LLM layer (TASK-015)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence

import pytest
from pydantic import BaseModel

from ecommerce_support.core.config import LLMConfig
from ecommerce_support.core.exceptions import (
    LLMAuthError,
    LLMCapabilityError,
    LLMError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from ecommerce_support.llm.capabilities import LLMCapability
from ecommerce_support.llm.providers.mock import MockLLMClient
from ecommerce_support.llm.retry import (
    RetryingLLMClient,
    RetryPolicy,
    backoff_delay,
    is_retryable,
    with_retries,
)
from ecommerce_support.llm.types import (
    ChatMessage,
    CompletionRequest,
    CompletionResponse,
    Role,
    StreamChunk,
    ToolCall,
    ToolDefinition,
)
from ecommerce_support.llm.usage import UsageTracker


def _request() -> CompletionRequest:
    return CompletionRequest(messages=[ChatMessage(role=Role.user, content="hi")])


def _policy(attempts: int = 3, *, base: float = 0.5, maximum: float = 8.0) -> RetryPolicy:
    return RetryPolicy(max_attempts=attempts, base_seconds=base, max_seconds=maximum, jitter=0.0)


class _RecordingSleeper:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


class _FlakyClient(MockLLMClient):
    """Mock client that fails a fixed number of times before succeeding."""

    def __init__(
        self,
        failures: int = 0,
        *,
        error_factory: type[LLMError] = LLMError,
        error: Exception | None = None,
    ) -> None:
        super().__init__(name="flaky-model")
        self.remaining_failures = failures
        self._error_factory = error_factory
        self._error = error
        self.attempts = 0

    def _maybe_fail(self) -> None:
        self.attempts += 1
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            if self._error is not None:
                raise self._error
            raise self._error_factory("transient failure")

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self._maybe_fail()
        return await super().complete(request)


class _FlakyStructuredClient(MockLLMClient):
    def __init__(self, failures: int) -> None:
        super().__init__(name="flaky-structured", structured_outputs=[{"a": 1}])
        self.remaining = failures
        self.attempts = 0

    async def structured(self, request: CompletionRequest, schema: type[BaseModel]) -> BaseModel:
        self.attempts += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise LLMTimeoutError("slow structured")
        return await super().structured(request, schema)


# --- policy helpers ---------------------------------------------------------


def test_from_config_maps_max_retries_to_attempts() -> None:
    policy = RetryPolicy.from_config(
        LLMConfig(max_retries=5, retry_backoff_base_seconds=0.25, retry_backoff_max_seconds=4.0)
    )
    assert policy.max_attempts == 5
    assert policy.base_seconds == 0.25
    assert policy.max_seconds == 4.0


def test_from_config_clamps_zero_retries_to_one_attempt() -> None:
    assert RetryPolicy.from_config(LLMConfig(max_retries=0)).max_attempts == 1


def test_is_retryable_matrix() -> None:
    assert is_retryable(LLMTimeoutError("t"))
    assert is_retryable(LLMRateLimitError("r"))
    assert is_retryable(LLMError("e", retryable=True))
    assert not is_retryable(LLMError("e", retryable=False))
    assert not is_retryable(LLMAuthError("a"))
    assert not is_retryable(LLMCapabilityError("c"))


def test_backoff_grows_exponentially_and_caps() -> None:
    policy = _policy(base=0.5, maximum=2.0)
    assert backoff_delay(1, policy, rng=lambda: 0.0) == 0.5
    assert backoff_delay(2, policy, rng=lambda: 0.0) == 1.0
    # Would be 2.0 at attempt 3, but capped at 2.0.
    assert backoff_delay(4, policy, rng=lambda: 0.0) == 2.0


def test_backoff_applies_jitter_within_bounds() -> None:
    policy = RetryPolicy(max_attempts=3, base_seconds=1.0, max_seconds=100.0, jitter=0.5)
    assert backoff_delay(1, policy, rng=lambda: 0.0) == pytest.approx(0.5)
    assert backoff_delay(1, policy, rng=lambda: 1.0) == pytest.approx(1.5)


# --- with_retries -----------------------------------------------------------


async def test_with_retries_recovers_after_transient_failures() -> None:
    sleeper = _RecordingSleeper()
    calls = {"n": 0}

    async def operation() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise LLMTimeoutError("slow")
        return "ok"

    result = await with_retries(
        operation, policy=_policy(3, base=0.5), sleep=sleeper, rng=lambda: 0.0
    )
    assert result == "ok"
    assert calls["n"] == 3
    assert sleeper.delays == [0.5, 1.0]


async def test_with_retries_stops_on_non_retryable() -> None:
    sleeper = _RecordingSleeper()
    calls = {"n": 0}

    async def operation() -> str:
        calls["n"] += 1
        raise LLMAuthError("nope")

    with pytest.raises(LLMAuthError):
        await with_retries(operation, policy=_policy(5), sleep=sleeper)
    assert calls["n"] == 1
    assert sleeper.delays == []


async def test_with_retries_exhausts_budget() -> None:
    sleeper = _RecordingSleeper()
    calls = {"n": 0}

    async def operation() -> str:
        calls["n"] += 1
        raise LLMRateLimitError("busy")

    with pytest.raises(LLMRateLimitError):
        await with_retries(operation, policy=_policy(3), sleep=sleeper, rng=lambda: 0.0)
    assert calls["n"] == 3
    assert len(sleeper.delays) == 2


async def test_with_retries_does_not_retry_programmer_errors() -> None:
    calls = {"n": 0}

    async def operation() -> str:
        calls["n"] += 1
        raise ValueError("bug")

    with pytest.raises(ValueError):
        await with_retries(operation, policy=_policy(3), sleep=_RecordingSleeper())
    assert calls["n"] == 1


async def test_single_attempt_policy_never_sleeps() -> None:
    sleeper = _RecordingSleeper()

    async def operation() -> str:
        raise LLMTimeoutError("slow")

    with pytest.raises(LLMTimeoutError):
        await with_retries(operation, policy=_policy(1), sleep=sleeper)
    assert sleeper.delays == []


async def test_on_retry_callback_receives_attempt_and_delay() -> None:
    events: list[tuple[int, float]] = []

    async def operation() -> str:
        raise LLMTimeoutError("slow")

    with pytest.raises(LLMTimeoutError):
        await with_retries(
            operation,
            policy=_policy(2, base=0.5),
            sleep=_RecordingSleeper(),
            rng=lambda: 0.0,
            on_retry=lambda attempt, delay, _exc: events.append((attempt, delay)),
        )
    assert events == [(1, 0.5)]


# --- RetryingLLMClient ------------------------------------------------------


async def test_client_retries_complete_and_records_usage() -> None:
    inner = _FlakyClient(failures=2, error_factory=LLMTimeoutError)
    tracker = UsageTracker()
    client = RetryingLLMClient(
        inner, _policy(3), timeout_seconds=5.0, tracker=tracker, sleep=_RecordingSleeper()
    )
    response = await client.complete(_request())
    assert inner.attempts == 3
    assert response.content.startswith("[mock]")
    records = tracker.records()
    assert len(records) == 1
    assert records[0].provider == "mock"
    assert records[0].model == "flaky-model"
    assert records[0].total_tokens == response.usage.total_tokens


async def test_client_fails_fast_on_auth_error() -> None:
    inner = _FlakyClient(failures=5, error_factory=LLMAuthError)
    client = RetryingLLMClient(inner, _policy(3), sleep=_RecordingSleeper())
    with pytest.raises(LLMAuthError):
        await client.complete(_request())
    assert inner.attempts == 1


async def test_client_enforces_per_call_timeout_and_retries_it() -> None:
    class _SlowClient(MockLLMClient):
        def __init__(self) -> None:
            super().__init__(name="slow")
            self.attempts = 0

        async def complete(self, request: CompletionRequest) -> CompletionResponse:
            self.attempts += 1
            await asyncio.sleep(5)
            return await super().complete(request)

    inner = _SlowClient()
    client = RetryingLLMClient(
        inner, _policy(2, base=0.001), timeout_seconds=0.02, sleep=_RecordingSleeper()
    )
    with pytest.raises(LLMTimeoutError):
        await client.complete(_request())
    assert inner.attempts == 2


async def test_client_does_not_retry_mid_stream_failure() -> None:
    class _StreamBoom(MockLLMClient):
        async def astream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
            yield StreamChunk(delta="partial")
            raise LLMTimeoutError("dropped mid-stream")

    client = RetryingLLMClient(_StreamBoom(), _policy(3), sleep=_RecordingSleeper())
    seen: list[StreamChunk] = []
    with pytest.raises(LLMTimeoutError):
        async for chunk in client.astream(_request()):
            seen.append(chunk)
    assert [c.delta for c in seen] == ["partial"]


async def test_client_records_stream_usage_from_terminal_chunk() -> None:
    tracker = UsageTracker()
    client = RetryingLLMClient(MockLLMClient(name="stream-model"), _policy(1), tracker=tracker)
    chunks = [c async for c in client.astream(_request())]
    assert chunks[-1].done is True
    records = tracker.records()
    assert len(records) == 1
    assert records[0].model == "stream-model"


async def test_client_records_tool_call_usage() -> None:
    tracker = UsageTracker()
    inner = MockLLMClient(
        name="tool-model",
        tool_call_responses=[[ToolCall(id="t1", name="t", arguments={})]],
    )
    client = RetryingLLMClient(inner, _policy(1), tracker=tracker)
    tools: Sequence[ToolDefinition] = [
        ToolDefinition(name="t", description="d", parameters={"type": "object"})
    ]
    await client.tool_call(_request(), tools)
    assert tracker.totals().calls == 1


async def test_client_without_tracker_does_not_fail() -> None:
    client = RetryingLLMClient(MockLLMClient(), _policy(1))
    response = await client.complete(_request())
    assert response.content


async def test_structured_is_retried() -> None:
    inner = _FlakyStructuredClient(failures=1)
    client = RetryingLLMClient(inner, _policy(3), sleep=_RecordingSleeper())

    class _Answer(BaseModel):
        a: int

    result = await client.structured(_request(), _Answer)
    assert result == _Answer(a=1)
    assert inner.attempts == 2


async def test_supports_and_require_delegate() -> None:
    client = RetryingLLMClient(MockLLMClient(), _policy(1))
    assert client.supports(LLMCapability.complete)
    with pytest.raises(LLMCapabilityError):
        client.require(LLMCapability.vision)


async def test_complete_delegates_model_name_and_unwrap() -> None:
    inner = MockLLMClient(name="inner-name")
    client = RetryingLLMClient(inner, _policy(1))
    assert client.model_name() == "inner-name"
    assert client.unwrap() is inner
