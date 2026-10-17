"""Readiness check registry (layer-neutral so ``db`` and ``api`` can both use it)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


ReadinessCheck = Callable[[], Awaitable[CheckResult]]

_checks: list[ReadinessCheck] = []


def register_readiness_check(check: ReadinessCheck) -> None:
    """Register an async readiness check (idempotent per callable)."""
    if check not in _checks:
        _checks.append(check)


def clear_readiness_checks() -> None:
    """Remove all registered checks (tests only)."""
    _checks.clear()


def snapshot_readiness_checks() -> list[ReadinessCheck]:
    """Return a copy of the current checks (tests use this to restore state)."""
    return list(_checks)


async def run_readiness_checks() -> list[CheckResult]:
    """Run every registered check; never raises."""
    results: list[CheckResult] = []
    for check in _checks:
        try:
            results.append(await check())
        except Exception as exc:  # readiness must never raise
            name = getattr(check, "__name__", "check")
            results.append(CheckResult(name, False, type(exc).__name__))
    return results
