"""In-process sliding-window rate limiting (NFR-004, SEC-012).

Framework-free and dependency-free so it can be unit-tested with an injected clock. A process-local
limiter is sufficient for a single instance; a shared store (Redis) is the drop-in upgrade for
horizontal scaling (noted as a limitation in ``TASKS.md``).
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

WINDOW_SECONDS = 60.0


@dataclass(frozen=True)
class RateLimitDecision:
    """Outcome of a rate-limit check for one key."""

    allowed: bool
    remaining: int
    retry_after_seconds: int


class SlidingWindowRateLimiter:
    """Counts events per key over a rolling window and rejects once the limit is reached."""

    def __init__(
        self,
        *,
        window_seconds: float = WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._window = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = {}

    def check(self, key: str, *, limit: int) -> RateLimitDecision:
        """Record an attempt for ``key`` and report whether it is allowed under ``limit``."""
        now = self._clock()
        cutoff = now - self._window
        bucket = self._events.get(key)
        if bucket is None:
            bucket = deque()
            self._events[key] = bucket
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

        if len(bucket) >= limit:
            retry = max(1, math.ceil(bucket[0] + self._window - now))
            return RateLimitDecision(allowed=False, remaining=0, retry_after_seconds=retry)

        bucket.append(now)
        return RateLimitDecision(
            allowed=True, remaining=max(0, limit - len(bucket)), retry_after_seconds=0
        )

    def reset(self, key: str | None = None) -> None:
        """Clear one key's window, or all keys when ``key`` is ``None`` (used by tests)."""
        if key is None:
            self._events.clear()
        else:
            self._events.pop(key, None)


_limiter: SlidingWindowRateLimiter | None = None


def get_rate_limiter() -> SlidingWindowRateLimiter:
    """Return the process-wide rate limiter (created on first use)."""
    global _limiter
    if _limiter is None:
        _limiter = SlidingWindowRateLimiter()
    return _limiter


def reset_rate_limiter() -> None:
    """Drop the cached limiter (used by tests to isolate windows)."""
    global _limiter
    _limiter = None


__all__ = [
    "RateLimitDecision",
    "SlidingWindowRateLimiter",
    "get_rate_limiter",
    "reset_rate_limiter",
]
