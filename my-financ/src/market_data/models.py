"""Collector interface and shared normalisation.

The rest of the system only ever sees :class:`Candle` and :class:`Ticker`, so
each collector is responsible for translating its venue's format into ours.
That keeps exchange quirks (Binance's compact ``BTCUSDT`` symbols, Coinbase's
candle arrays) out of the strategy and agent layers.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field

from src.core.enums import Timeframe
from src.schemas.market import Candle, MarketSnapshot, Ticker


@dataclass(slots=True)
class CollectorCapabilities:
    """What a venue supports. Used to fail fast on unsupported requests."""

    spot: bool = True
    futures: bool = False
    websocket: bool = False
    historical_limit: int = 1000
    supports_orderbook: bool = False
    supports_trades: bool = False


@dataclass(slots=True)
class NormalizationReport:
    """Diagnostics from normalising raw venue payloads.

    Rows dropped during normalisation are reported rather than silently
    discarded: a gap in a candle series quietly shifts every indicator.
    """

    received: int = 0
    accepted: int = 0
    dropped: int = 0
    duplicates: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def drop_rate(self) -> float:
        return self.dropped / self.received if self.received else 0.0


def normalize_candles(
    raw: list[dict],
    *,
    symbol: str,
    timeframe: Timeframe,
    source: str = "unknown",
) -> tuple[list[Candle], NormalizationReport]:
    """Convert raw OHLCV dicts into validated candles.

    Drops rows that fail validation (missing price, non-positive price,
    high < low) and de-duplicates by timestamp, reporting both.
    """
    report = NormalizationReport(received=len(raw))
    seen: set[int] = set()
    candles: list[Candle] = []

    for index, row in enumerate(raw):
        try:
            timestamp = row["timestamp"]
            if isinstance(timestamp, (int, float)):
                from datetime import datetime, timezone

                timestamp = datetime.fromtimestamp(timestamp / 1000, tz=timezone.utc)
            elif isinstance(timestamp, str):
                from datetime import datetime

                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

            candle = Candle(
                timestamp=timestamp,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", 0.0) or 0.0),
                symbol=symbol,
                timeframe=timeframe,
            )
        except (KeyError, TypeError, ValueError) as exc:
            report.dropped += 1
            if len(report.warnings) < 5:
                report.warnings.append(f"row {index}: {exc}")
            continue

        key = int(candle.timestamp.timestamp())
        if key in seen:
            report.duplicates += 1
            continue
        seen.add(key)
        candles.append(candle)
        report.accepted += 1

    candles.sort(key=lambda c: c.timestamp)
    if not candles:
        report.warnings.append(f"no valid candles from {source}")
    return candles, report


def build_snapshot(
    symbol: str,
    candles: list[Candle],
    ticker: Ticker,
) -> MarketSnapshot:
    return MarketSnapshot(symbol=symbol, ticker=ticker, candles=candles)


class BaseCollector(abc.ABC):
    """Abstract market-data source."""

    name: str = "base"
    capabilities: CollectorCapabilities = CollectorCapabilities()

    @abc.abstractmethod
    async def fetch_candles(
        self, symbol: str, timeframe: Timeframe, limit: int = 500
    ) -> list[Candle]:
        """Return closed candles in ascending time order."""

    @abc.abstractmethod
    async def fetch_ticker(self, symbol: str) -> Ticker:
        """Return the latest price for a symbol."""

    async def fetch_snapshot(
        self, symbol: str, timeframe: Timeframe = Timeframe.H1, limit: int = 500
    ) -> MarketSnapshot:
        """Default snapshot implementation: candles plus ticker in parallel."""
        import asyncio

        candles, ticker = await asyncio.gather(
            self.fetch_candles(symbol, timeframe, limit),
            self.fetch_ticker(symbol),
        )
        return build_snapshot(symbol, candles, ticker)

    async def close(self) -> None:
        """Release any underlying HTTP resources."""
        return None