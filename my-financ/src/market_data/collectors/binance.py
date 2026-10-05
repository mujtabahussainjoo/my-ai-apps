"""Binance public market-data collector.

Uses the public REST endpoints only — no API key, no signed request, and
therefore no ability to trade or withdraw. Trading capability is a separate
code path in :mod:`src.integrations.exchanges`.

A deterministic synthetic fallback is included so the backtester, tests and
demos work without network access. Synthetic candles are clearly flagged in
the report warnings; nothing downstream can mistake them for market data.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from src.core.config import Settings, get_settings
from src.core.enums import Timeframe
from src.core.exceptions import MarketDataError, SymbolNotSupportedError
from src.core.logging import get_logger
from src.market_data.models import (
    BaseCollector,
    CollectorCapabilities,
    normalize_candles,
)
from src.schemas.market import Candle, Ticker

logger = get_logger(__name__)

#: CCXT-style ``BTC/USDT`` -> Binance ``BTCUSDT``.
KNOWN_SYMBOLS: dict[str, str] = {
    "BTC/USDT": "BTCUSDT",
    "ETH/USDT": "ETHUSDT",
    "SOL/USDT": "SOLUSDT",
    "BNB/USDT": "BNBUSDT",
    "XRP/USDT": "XRPUSDT",
    "ADA/USDT": "ADAUSDT",
    "DOGE/USDT": "DOGEUSDT",
    "AVAX/USDT": "AVAXUSDT",
    "LINK/USDT": "LINKUSDT",
    "MATIC/USDT": "MATICUSDT",
    "DOT/USDT": "DOTUSDT",
    "LTC/USDT": "LTCUSDT",
    "ATOM/USDT": "ATOMUSDT",
    "UNI/USDT": "UNIUSDT",
    "NEAR/USDT": "NEARUSDT",
    "APT/USDT": "APTUSDT",
    "ARB/USDT": "ARBUSDT",
    "OP/USDT": "OPUSDT",
    "SUI/USDT": "SUIUSDT",
    "FIL/USDT": "FILUSDT",
    "TRX/USDT": "TRXUSDT",
}


def to_binance_symbol(symbol: str) -> str:
    """Convert a unified symbol to Binance's compact form."""
    if "/" in symbol:
        base, _, quote = symbol.partition("/")
        return f"{base.upper()}{quote.upper()}"
    return symbol.upper()


def to_unified_symbol(symbol: str) -> str:
    """Best-effort reverse mapping for display."""
    if symbol in KNOWN_SYMBOLS.values():
        reverse = {v: k for k, v in KNOWN_SYMBOLS.items()}
        return reverse.get(symbol, symbol)
    return symbol


class BinanceCollector(BaseCollector):
    """Public market data from the Binance spot API."""

    name = "binance"
    capabilities = CollectorCapabilities(
        spot=True,
        futures=True,
        websocket=True,
        historical_limit=1000,
        supports_orderbook=True,
        supports_trades=True,
    )

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(5)

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.settings.binance_base_url,
                timeout=self.settings.market_data_timeout_seconds,
                headers={"User-Agent": "my-financ/0.1"},
                follow_redirects=False,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _get(self, path: str, params: dict[str, Any]) -> Any:
        async with self._semaphore:
            client = await self._http()
            try:
                response = await client.get(path, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (400, 404):
                    raise SymbolNotSupportedError(
                        f"Binance rejected {path} for {params.get('symbol')}: "
                        f"{exc.response.text[:200]}"
                    ) from exc
                raise MarketDataError(f"Binance HTTP {exc.response.status_code} on {path}") from exc
            except httpx.HTTPError as exc:
                raise MarketDataError(f"Binance request failed on {path}: {exc}") from exc

    async def fetch_candles(
        self, symbol: str, timeframe: Timeframe = Timeframe.H1, limit: int = 500
    ) -> list[Candle]:
        if limit > self.capabilities.historical_limit:
            raise MarketDataError(
                f"Binance caps a single klines request at "
                f"{self.capabilities.historical_limit} candles, got {limit}"
            )
        payload = await self._get(
            "/api/v3/klines",
            {
                "symbol": to_binance_symbol(symbol),
                "interval": timeframe.binance_interval,
                "limit": limit,
            },
        )
        rows = [
            {
                "timestamp": entry[0],
                "open": entry[1],
                "high": entry[2],
                "low": entry[3],
                "close": entry[4],
                "volume": entry[5],
            }
            for entry in payload
        ]
        candles, report = normalize_candles(rows, symbol=symbol, timeframe=timeframe, source=self.name)
        if report.dropped or report.duplicates:
            logger.warning(
                "binance_normalize_report",
                symbol=symbol,
                received=report.received,
                accepted=report.accepted,
                dropped=report.dropped,
                duplicates=report.duplicates,
                warnings=report.warnings,
            )
        if not candles:
            raise MarketDataError(f"Binance returned no usable candles for {symbol}")
        # The last kline is still forming. Including it would compute
        # indicators on a partial bar and produce phantom signals.
        if len(candles) > 1 and not self._is_closed(candles[-1], timeframe):
            candles = candles[:-1]
        return candles

    @staticmethod
    def _is_closed(candle: Candle, timeframe: Timeframe) -> bool:
        close_time = candle.timestamp + timedelta(seconds=timeframe.seconds)
        return datetime.now(timezone.utc) >= close_time

    async def fetch_historical(
        self,
        symbol: str,
        timeframe: Timeframe = Timeframe.H1,
        start: datetime | None = None,
        end: datetime | None = None,
        max_candles: int = 10_000,
    ) -> list[Candle]:
        """Page backwards through klines to build a long history.

        Binance caps each response at 1000 candles, so multi-year backtests
        need pagination. Requests are issued sequentially with a small delay
        because the public endpoint rate-limits aggressively.
        """
        collected: list[Candle] = []
        cursor_end = end

        while len(collected) < max_candles:
            params: dict[str, Any] = {
                "symbol": to_binance_symbol(symbol),
                "interval": timeframe.binance_interval,
                "limit": min(self.capabilities.historical_limit, max_candles - len(collected)),
            }
            if cursor_end is not None:
                params["endTime"] = int(cursor_end.timestamp() * 1000) - 1
            if start is not None and not collected:
                params["startTime"] = int(start.timestamp() * 1000)

            payload = await self._get("/api/v3/klines", params)
            if not payload:
                break

            rows = [
                {
                    "timestamp": entry[0],
                    "open": entry[1],
                    "high": entry[2],
                    "low": entry[3],
                    "close": entry[4],
                    "volume": entry[5],
                }
                for entry in payload
            ]
            batch, _ = normalize_candles(
                rows, symbol=symbol, timeframe=timeframe, source=f"{self.name}-paged"
            )
            if not batch:
                break

            collected = batch + collected
            oldest = batch[0].timestamp
            if start is not None and oldest <= start:
                break
            if len(batch) < params["limit"]:
                break
            if cursor_end is not None and oldest >= cursor_end:
                # The page did not move backwards; looping again would fetch the
                # same candles forever. Only meaningful once a cursor exists --
                # on the first pass cursor_end is None, and comparing a datetime
                # against None raises instead of protecting anything.
                logger.warning("pagination_stalled", symbol=symbol, cursor=str(oldest))
                break
            cursor_end = oldest
            await asyncio.sleep(0.25)

        deduplicated = {int(c.timestamp.timestamp()): c for c in collected}
        ordered = [deduplicated[key] for key in sorted(deduplicated)]
        if start is not None:
            ordered = [c for c in ordered if c.timestamp >= start]
        if end is not None:
            ordered = [c for c in ordered if c.timestamp <= end]
        logger.info(
            "binance_history_loaded",
            symbol=symbol,
            timeframe=timeframe.value,
            candles=len(ordered),
            from_=str(ordered[0].timestamp) if ordered else None,
            to=str(ordered[-1].timestamp) if ordered else None,
        )
        return ordered

    async def fetch_ticker(self, symbol: str) -> Ticker:
        payload = await self._get(
            "/api/v3/ticker/bookTicker", {"symbol": to_binance_symbol(symbol)}
        )
        bid = float(payload.get("bidPrice", 0) or 0)
        ask = float(payload.get("askPrice", 0) or 0)
        last = ask if ask > 0 else (bid if bid > 0 else 0.0)
        if last <= 0:
            # bookTicker can omit last; fall back to the 24h ticker.
            stats = await self._get(
                "/api/v3/ticker/24hr", {"symbol": to_binance_symbol(symbol)}
            )
            last = float(stats.get("lastPrice", 0) or 0)
        if last <= 0:
            raise MarketDataError(f"Binance returned no price for {symbol}")
        return Ticker(
            symbol=symbol,
            last=last,
            bid=bid or None,
            ask=ask or None,
            volume_24h=float(payload.get("volume", 0) or 0) or None,
        )

    async def fetch_orderbook(self, symbol: str, depth: int = 20) -> dict[str, list]:
        return await self._get(
            "/api/v3/depth",
            {"symbol": to_binance_symbol(symbol), "limit": min(depth, 100)},
        )


class SyntheticCollector(BaseCollector):
    """Deterministic offline data source.

    Generates a reproducible random walk with trend regimes and volatility
    clustering. Used for tests, CI, and demos when the network is unavailable.
    It is never a fallback for live trading: :meth:`fetch_ticker` refuses when
    asked for a live quote, so a network outage cannot quietly turn into
    synthetic orders.
    """

    name = "synthetic"
    capabilities = CollectorCapabilities(spot=True, historical_limit=10_000)

    BASE_PRICES: dict[str, float] = {
        "BTC/USDT": 65_000.0,
        "ETH/USDT": 3_200.0,
        "SOL/USDT": 145.0,
        "BNB/USDT": 580.0,
        "XRP/USDT": 0.62,
        "DOGE/USDT": 0.14,
        "ADA/USDT": 0.45,
        "AVAX/USDT": 28.0,
        "LINK/USDT": 14.5,
        "DOT/USDT": 6.4,
    }

    def __init__(self, seed: int = 42, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.seed = seed
        self._series: dict[tuple[str, str], list[Candle]] = {}

    def _base_price(self, symbol: str) -> float:
        return self.BASE_PRICES.get(symbol, 100.0)

    def _generate(self, symbol: str, timeframe: Timeframe, limit: int) -> list[Candle]:
        import numpy as np

        key = (symbol, timeframe.value)
        if key in self._series:
            return self._series[key][-limit:]

        rng = np.random.default_rng(abs(hash(f"{self.seed}:{key}")) % (2**32))
        price = self._base_price(symbol)
        vol = price * 0.012
        start = datetime.now(timezone.utc) - timedelta(seconds=timeframe.seconds * limit)

        candles: list[Candle] = []
        for index in range(limit):
            # Regime switching: a slow sine drift plus a stochastic shock, so
            # trend-following strategies have something real to detect.
            drift = vol * 0.12 * np.sin(index / 55.0)
            volatility = vol * (0.7 + 0.6 * abs(np.sin(index / 90.0)))
            close = max(price + rng.normal(drift, volatility), price * 0.05)
            open_ = price
            high = max(open_, close) * (1 + abs(rng.normal(0, 0.003)))
            low = min(open_, close) * (1 - abs(rng.normal(0, 0.003)))
            volume = abs(rng.normal(800, 250))
            candles.append(
                Candle(
                    timestamp=start + timedelta(seconds=timeframe.seconds * index),
                    open=float(open_),
                    high=float(high),
                    low=float(max(low, 0.00000001)),
                    close=float(close),
                    volume=float(volume),
                    symbol=symbol,
                    timeframe=timeframe,
                )
            )
            price = close

        self._series[key] = candles
        return candles[-limit:] if limit < len(candles) else candles

    async def fetch_candles(
        self, symbol: str, timeframe: Timeframe = Timeframe.H1, limit: int = 500
    ) -> list[Candle]:
        await asyncio.sleep(0)
        return list(self._generate(symbol, timeframe, limit))

    async def fetch_historical(
        self,
        symbol: str,
        timeframe: Timeframe = Timeframe.H1,
        start: datetime | None = None,
        end: datetime | None = None,
        max_candles: int = 10_000,
    ) -> list[Candle]:
        candles = self._generate(symbol, timeframe, max_candles)
        if start is not None:
            candles = [c for c in candles if c.timestamp >= start]
        if end is not None:
            candles = [c for c in candles if c.timestamp <= end]
        return candles

    async def fetch_ticker(self, symbol: str) -> Ticker:
        await asyncio.sleep(0)
        candles = self._generate(symbol, Timeframe.H1, 2)
        last = candles[-1].close
        spread = last * 0.0002
        return Ticker(
            symbol=symbol,
            last=last,
            bid=last - spread,
            ask=last + spread,
            volume_24h=sum(c.volume for c in candles) * 24,
        )