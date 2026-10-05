"""TradingView alert parsing.

TradingView sends an arbitrary JSON body whose shape the sender controls, so
every field here is treated as hostile: values are parsed defensively, unknown
fields are kept but never interpreted, and nothing in this module is allowed to
decide that a trade should happen.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from src.core.enums import Timeframe
from src.core.logging import get_logger
from src.schemas.signal import SignalAction

logger = get_logger(__name__)

#: Actions we recognise. Anything else is rejected rather than guessed at.
_ALLOWED_ACTIONS = {
    "buy": SignalAction.BUY,
    "sell": SignalAction.SELL,
    "close": SignalAction.SELL,
    "exit": SignalAction.SELL,
    "hold": SignalAction.HOLD,
}


class WebhookSignal(BaseModel):
    """One validated TradingView alert.

    This is an *input*, not a decision: ``action`` says what the alert author
    wanted, and the risk engine still gets the final say.
    """

    symbol: str = Field(..., min_length=2, max_length=32)
    action: SignalAction
    timeframe: Timeframe = Timeframe.H1
    strategy: str = Field("tradingview", max_length=64)
    price: float | None = Field(None, gt=0.0)
    stop_loss: float | None = Field(None, gt=0.0)
    take_profit: float | None = Field(None, gt=0.0)
    confidence: float | None = Field(None, ge=0.0, le=1.0)
    secret_time: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @field_validator("symbol")
    @classmethod
    def _normalise_symbol(cls, value: str) -> str:
        """Accept BINANCE:BTCUSDT style ids as well as BTC/USDT."""
        cleaned = value.strip().upper()
        if ":" in cleaned:
            cleaned = cleaned.split(":", 1)[1]
        if "/" not in cleaned and cleaned.endswith(("USDT", "USDC", "USD")):
            quote = "USDT" if cleaned.endswith("USDT") else ("USDC" if cleaned.endswith("USDC") else "USD")
            cleaned = f"{cleaned[: -len(quote)]}/{quote}"
        return cleaned

    @property
    def is_actionable(self) -> bool:
        return self.action is not SignalAction.HOLD


def parse_webhook(body: dict[str, Any]) -> WebhookSignal:
    """Turn a raw alert body into a validated signal.

    Raises ``ValueError`` with a specific message when the payload cannot be
    trusted, so the caller can return a 4xx rather than guessing.
    """
    if not isinstance(body, dict):
        raise ValueError("webhook body must be a JSON object")

    action_raw = str(body.get("action", body.get("side", ""))).strip().lower()
    if not action_raw:
        raise ValueError("webhook is missing 'action'")

    action = _ALLOWED_ACTIONS.get(action_raw)
    if action is None:
        raise ValueError(
            f"unrecognised action {action_raw!r}; expected one of {sorted(_ALLOWED_ACTIONS)}"
        )

    symbol = body.get("symbol") or body.get("ticker") or body.get("s")
    if not symbol:
        raise ValueError("webhook is missing 'symbol'")

    timeframe_raw = str(body.get("timeframe", body.get("interval", "60")))
    try:
        timeframe = Timeframe(_normalise_timeframe(timeframe_raw))
    except ValueError as exc:
        raise ValueError(f"unknown timeframe {timeframe_raw!r}") from exc

    def _number(key: str) -> float | None:
        value = body.get(key)
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{key!r} must be a number, got {value!r}") from exc

    return WebhookSignal(
        symbol=str(symbol),
        action=action,
        timeframe=timeframe,
        strategy=str(body.get("strategy", "tradingview"))[:64],
        price=_number("price"),
        stop_loss=_number("stop_loss") or _number("sl"),
        take_profit=_number("take_profit") or _number("tp"),
        confidence=_number("confidence"),
        secret_time=body.get("secret") if isinstance(body.get("secret"), int) else None,
        raw=body,
    )


def _normalise_timeframe(value: str) -> str:
    """TradingView sends minutes as bare integers ("60", "240")."""
    cleaned = value.strip().lower()
    if cleaned.isdigit():
        minutes = int(cleaned)
        mapping = {1: "1m", 3: "3m", 5: "5m", 15: "15m", 30: "30m", 60: "1h", 120: "2h", 240: "4h", 360: "6h", 480: "8h", 720: "12h", 1440: "1d"}
        return mapping.get(minutes, f"{minutes}m")
    return cleaned


def received_at() -> datetime:
    return datetime.now(UTC)


__all__ = ["WebhookSignal", "parse_webhook", "received_at"]
