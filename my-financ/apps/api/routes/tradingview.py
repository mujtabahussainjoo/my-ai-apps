"""The TradingView webhook endpoint.

Three things happen here and nothing else: the request is authenticated, it is
replay-protected, and the alert is recorded. It does **not** place an order.

Routing an alert straight into execution would mean anyone who learned the
webhook secret could trade the account, and it would skip the risk gate. The
signal is written and the trading loop picks it up through the same assessed
path as every other signal.
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from src.core.enums import SignalAction
from src.core.logging import get_logger
from src.core.security import (
    ReplayGuard,
    assert_no_secrets,
    canonical_payload_hash,
    verify_shared_secret,
)
from src.integrations.tradingview.webhook import parse_webhook
from src.schemas.base import utcnow
from src.schemas.signal import Signal

from apps.api.dependencies import EventsDep, SettingsDep, SignalsDep

logger = get_logger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

#: Alerts are idempotent by content within the replay window: TradingView
#: retries deliveries, and a retry must not become a second signal. Guards are
#: keyed by window length and built from the injected settings rather than a
#: module-level snapshot, so the effective configuration is always the one the
#: app was started with.
_guards: dict[int, ReplayGuard] = {}


def _parse_body(raw: bytes) -> Any:
    """Decode the alert body, refusing anything that is not a JSON object."""
    try:
        payload = json.loads(raw.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"alert body is not valid JSON: {exc.msg}",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="alert body must be a JSON object",
        )
    return payload


def _guard_for(window_seconds: int) -> ReplayGuard:
    guard = _guards.get(window_seconds)
    if guard is None:
        guard = ReplayGuard(window_seconds=window_seconds)
        _guards[window_seconds] = guard
    return guard


@router.post("/tradingview")
async def tradingview_webhook(
    request: Request,
    settings: SettingsDep,
    events: EventsDep,
    signals: SignalsDep,
) -> dict[str, Any]:
    """Accept, verify, and record a TradingView alert."""
    raw = await request.body()
    if len(raw) > settings.webhook_max_body_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"webhook body exceeds {settings.webhook_max_body_bytes} bytes; "
                f"alerts should be small"
            ),
        )

    payload = _parse_body(raw)

    # TradingView cannot set a custom header, so the documented way to
    # authenticate a real alert is "secret" inside the JSON body. The header and
    # query forms are accepted too, for anything that can set them.
    provided = (
        request.headers.get("x-webhook-secret")
        or request.query_params.get("secret")
        or (payload.get("secret") if isinstance(payload, dict) else None)
    )
    if not verify_shared_secret(provided, settings.tradingview_webhook_secret):
        events.log(
            "warning",
            "webhook_rejected",
            "webhook secret missing or incorrect",
            level="warning",
            context={"remote": request.client.host if request.client else None},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid webhook secret"
        )

    # Verified: drop it before anything is stored, hashed, or scanned, so the
    # credential never reaches a log line or the replay guard.
    if isinstance(payload, dict):
        payload.pop("secret", None)

    # Scan after removing the secret. Scanning first would reject the very
    # documented body-secret form as a leaked credential.
    try:
        assert_no_secrets(
            json.dumps(payload, default=str), context="tradingview webhook"
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    fingerprint = canonical_payload_hash(json.dumps(payload, sort_keys=True, default=str).encode())
    guard = _guard_for(settings.webhook_replay_window_seconds)
    if not guard.check_and_record(fingerprint, now=time.time()):
        events.log(
            "warning",
            "webhook_replay_rejected",
            "duplicate alert within the replay window",
            level="warning",
            context={"fingerprint": fingerprint[:16]},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="this alert was already received within the replay window",
        )

    try:
        alert = parse_webhook(payload)
    except ValueError as exc:
        events.log("warning", "webhook_invalid", str(exc), level="warning")
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not alert.is_actionable:
        events.log(
            "info",
            "webhook_hold",
            f"non-actionable alert for {alert.symbol}",
            context={"symbol": alert.symbol, "action": alert.action.value},
        )
        return {"status": "ignored", "reason": "action is not actionable", "symbol": alert.symbol}

    if alert.price is None:
        raise HTTPException(
            status_code=422, detail="'price' is required: an alert without a price cannot be assessed"
        )

    signal = Signal(
        symbol=alert.symbol,
        timeframe=alert.timeframe,
        strategy=alert.strategy,
        action=alert.action,
        confidence=alert.confidence or 0.5,
        entry=alert.price,
        stop_loss=alert.stop_loss,
        take_profit=alert.take_profit,
        created_at=utcnow(),
    )
    signal_id = signals.record(signal)
    events.session.commit()

    events.log(
        "info",
        "webhook_accepted",
        f"alert recorded: {alert.action.value} {alert.symbol}",
        context={"symbol": alert.symbol, "signal_id": signal_id, "action": alert.action.value},
    )
    logger.info("tradingview_webhook_accepted", symbol=alert.symbol, signal_id=signal_id)

    return {
        "status": "recorded",
        "signal_id": signal_id,
        "symbol": alert.symbol,
        "action": alert.action.value,
        "note": (
            "The alert was recorded, not executed. Orders only reach a venue "
            "through the risk engine."
        ),
    }


@router.get("/tradingview/configured")
def webhook_configured(settings: SettingsDep) -> dict[str, Any]:
    """Whether webhooks will be accepted, without revealing the secret."""
    return {
        "configured": settings.tradingview_webhook_secret is not None,
        "replay_window_seconds": settings.webhook_replay_window_seconds,
        "max_body_bytes": settings.webhook_max_body_bytes,
        "actionable": [a.value for a in SignalAction],
    }


__all__ = ["router"]
