"""Market data providers.

Two public data sources are supported:

* **Stooq** — end-of-day quotes, no API key, clearly delayed.
* **Yahoo Finance chart API** — intraday/quote metadata, no API key.

Both are unofficial/public endpoints: the API always reports the source, the
retrieval time and the data's own timestamp so stale data is never presented as
live.
"""

from __future__ import annotations

import abc
import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from nexapilot.core.errors import ExternalServiceNotConfiguredError, IntegrationError
from nexapilot.core.logging import get_logger
from nexapilot.providers.http import classify_status, wrap_transport_error

log = get_logger(__name__)


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: float
    currency: str = "USD"
    source: str = ""
    as_of: datetime | None = None
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    market_status: str = "unknown"
    delay_note: str = ""
    previous_close: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_delayed(self) -> bool:
        return self.market_status not in ("live", "open")

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "currency": self.currency,
            "source": self.source,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "retrieved_at": self.retrieved_at.isoformat(),
            "market_status": self.market_status,
            "is_delayed": self.is_delayed,
            "delay_note": self.delay_note,
            "previous_close": self.previous_close,
            "day_high": self.day_high,
            "day_low": self.day_low,
        }


class QuoteProvider(abc.ABC):
    id: str = "quote"

    @abc.abstractmethod
    async def quote(self, symbol: str) -> Quote: ...


class StooqQuoteProvider(QuoteProvider):
    """End-of-day quotes from Stooq. No API key required."""

    id = "stooq"

    def __init__(self, *, timeout: float = 20.0, transport: Any = None) -> None:
        self._timeout = timeout
        self._transport = transport

    async def quote(self, symbol: str) -> Quote:
        url = "https://stooq.com/q/l/"
        params = {"s": symbol.lower(), "f": "sd2t2ohlcv", "h": "", "e": "csv"}
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport, follow_redirects=False
        ) as client:
            try:
                response = await client.get(url, params=params)
            except httpx.HTTPError as exc:
                raise wrap_transport_error(exc, "Stooq", self._timeout) from exc
            if response.status_code >= 400:
                raise classify_status(response.status_code, "Stooq", response.text)
            body = response.text

        rows = list(csv.DictReader(io.StringIO(body)))
        if not rows or "Close" not in rows[0]:
            raise IntegrationError(
                f"No quote available for '{symbol}'",
                details={"symbol": symbol, "source": self.id},
            )
        row = rows[0]
        close = _to_float(row.get("Close"))
        if close is None:
            raise IntegrationError(
                f"No closing price available for '{symbol}'",
                details={"symbol": symbol, "source": self.id},
            )
        as_of = _combine_date_time(row.get("Date"), row.get("Time"))
        return Quote(
            symbol=symbol.upper(),
            price=close,
            currency="USD",
            source="stooq",
            as_of=as_of,
            market_status="closed",
            delay_note="End-of-day (delayed) price from Stooq; not a live tick.",
            previous_close=_to_float(row.get("Open")),
            day_high=_to_float(row.get("High")),
            day_low=_to_float(row.get("Low")),
            raw={"row": row},
        )


class YahooQuoteProvider(QuoteProvider):
    """Quote metadata from the Yahoo Finance chart endpoint. No API key required."""

    id = "yahoo"

    def __init__(self, *, timeout: float = 20.0, transport: Any = None) -> None:
        self._timeout = timeout
        self._transport = transport

    async def quote(self, symbol: str) -> Quote:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        params = {"range": "5d", "interval": "1d"}
        async with httpx.AsyncClient(
            timeout=self._timeout,
            transport=self._transport,
            follow_redirects=False,
            headers={"User-Agent": "NexaPilotAI/0.1 (+desktop finance agent)"},
        ) as client:
            try:
                response = await client.get(url, params=params)
            except httpx.HTTPError as exc:
                raise wrap_transport_error(exc, "Yahoo Finance", self._timeout) from exc
            if response.status_code >= 400:
                raise classify_status(response.status_code, "Yahoo Finance", response.text)
            data = response.json()

        results = (data.get("chart") or {}).get("result") or []
        if not results:
            raise IntegrationError(
                f"No quote available for '{symbol}'",
                details={"symbol": symbol, "source": self.id},
            )
        meta = results[0].get("meta") or {}
        price = meta.get("regularMarketPrice")
        if price is None:
            raise IntegrationError(
                f"No price available for '{symbol}'",
                details={"symbol": symbol, "source": self.id},
            )
        timestamp = meta.get("regularMarketTime")
        as_of = (
            datetime.fromtimestamp(float(timestamp), tz=UTC)
            if isinstance(timestamp, (int, float))
            else None
        )
        market_status = str(meta.get("marketState") or "unknown").lower()
        return Quote(
            symbol=str(meta.get("symbol") or symbol).upper(),
            price=float(price),
            currency=str(meta.get("currency") or "USD"),
            source="yahoo",
            as_of=as_of,
            market_status=market_status,
            delay_note=(
                "Yahoo Finance quote data; exchanges and the feed itself may delay prices."
            ),
            previous_close=_to_float(meta.get("chartPreviousClose") or meta.get("previousClose")),
            day_high=_to_float(meta.get("regularMarketDayHigh")),
            day_low=_to_float(meta.get("regularMarketDayLow")),
            raw={"meta": {k: v for k, v in meta.items() if k != "currentTradingPeriod"}},
        )


def build_quote_provider(
    provider: str, *, timeout: float = 20.0, transport: Any = None
) -> QuoteProvider:
    if provider == "stooq":
        return StooqQuoteProvider(timeout=timeout, transport=transport)
    if provider == "yahoo":
        return YahooQuoteProvider(timeout=timeout, transport=transport)
    raise ExternalServiceNotConfiguredError(
        "No market data provider is configured.",
        setup_hint="Set NEXAPILOT_FINANCE_PROVIDER to 'stooq' or 'yahoo'.",
    )


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _combine_date_time(date_value: Any, time_value: Any) -> datetime | None:
    if not date_value or not isinstance(date_value, str):
        return None
    text = date_value.strip()
    if time_value and isinstance(time_value, str) and time_value.strip():
        text = f"{text}T{time_value.strip()}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
