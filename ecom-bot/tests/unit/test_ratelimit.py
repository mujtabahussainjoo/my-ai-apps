"""Unit tests for the in-process sliding-window rate limiter (TASK-038, NFR-004/SEC-012)."""

from __future__ import annotations

from ecommerce_support.core.ratelimit import (
    SlidingWindowRateLimiter,
    get_rate_limiter,
    reset_rate_limiter,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _limiter() -> tuple[SlidingWindowRateLimiter, _Clock]:
    clock = _Clock()
    return SlidingWindowRateLimiter(window_seconds=60.0, clock=clock), clock


def test_allows_up_to_limit_then_denies() -> None:
    limiter, _ = _limiter()
    for _ in range(3):
        decision = limiter.check("u-1", limit=3)
        assert decision.allowed is True
    denied = limiter.check("u-1", limit=3)
    assert denied.allowed is False
    assert denied.remaining == 0
    assert denied.retry_after_seconds >= 1


def test_keys_are_isolated() -> None:
    limiter, _ = _limiter()
    for _ in range(3):
        limiter.check("u-1", limit=3)
    assert limiter.check("u-1", limit=3).allowed is False
    assert limiter.check("u-2", limit=3).allowed is True


def test_window_slides_after_expiry() -> None:
    limiter, clock = _limiter()
    for _ in range(2):
        limiter.check("u-1", limit=2)
    assert limiter.check("u-1", limit=2).allowed is False
    clock.advance(61)
    assert limiter.check("u-1", limit=2).allowed is True


def test_remaining_counts_down() -> None:
    limiter, _ = _limiter()
    assert limiter.check("u-1", limit=5).remaining == 4
    assert limiter.check("u-1", limit=5).remaining == 3


def test_reset_clears_one_or_all_keys() -> None:
    limiter, _ = _limiter()
    limiter.check("u-1", limit=1)
    limiter.check("u-2", limit=1)
    limiter.reset("u-1")
    assert limiter.check("u-1", limit=1).allowed is True
    assert limiter.check("u-2", limit=1).allowed is False
    limiter.reset()
    assert limiter.check("u-2", limit=1).allowed is True


def test_singleton_is_reused_until_reset() -> None:
    reset_rate_limiter()
    first = get_rate_limiter()
    assert get_rate_limiter() is first
    reset_rate_limiter()
    assert get_rate_limiter() is not first
