"""Health and readiness endpoints.

``/health`` is a liveness probe (process is up). ``/ready`` runs registered readiness checks
(config, database, …) — see :mod:`ecommerce_support.core.readiness` for the registry.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from ecommerce_support import __version__
from ecommerce_support.core.config import get_settings
from ecommerce_support.core.logging import get_logger
from ecommerce_support.core.readiness import (
    CheckResult,
    ReadinessCheck,
    clear_readiness_checks,
    register_readiness_check,
    run_readiness_checks,
)

__all__ = [
    "CheckResult",
    "ReadinessCheck",
    "clear_readiness_checks",
    "register_readiness_check",
]

router = APIRouter(tags=["health"])
_log = get_logger(__name__)


async def _check_configuration() -> CheckResult:
    try:
        settings = get_settings()
    except Exception as exc:
        return CheckResult("config", False, f"{type(exc).__name__}: {exc}")
    return CheckResult("config", True, f"env={settings.app.env.value}")


register_readiness_check(_check_configuration)


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, object]:
    return {"status": "ok", "service": "ecommerce-support", "version": __version__}


@router.get("/ready", summary="Readiness probe")
async def ready(response: Response) -> dict[str, object]:
    checks = await run_readiness_checks()
    ready_now = all(c.ok for c in checks)
    if not ready_now:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        _log.warning(
            "readiness_failed",
            checks=[{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks],
        )
    return {
        "status": "ready" if ready_now else "not_ready",
        "checks": {c.name: {"ok": c.ok, "detail": c.detail} for c in checks},
    }
