"""Coinbase public market-data collector."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from src.core.enums import Timeframe
from src.core.exceptions import MarketDataError, SymbolNotSupportedError
from src.market_data.models import BaseCollector, CollectorCapabilities, normalize_candles
from src.schemas.market import Candle, Ticker

COINBASE_BASE = "https://api.exchange.coinbase.com"

#: Coinbase uses single-asset product ids and needs its own granularity map.
GRANULARITY: dict[Timeframe, int] = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M15: 900,
    Timeframe.H1: 3600,
    Timeframe.H4: 14400,
    Timeframe.D1: 86400,
}


class CoinbaseCollector(BaseCollector):
    name = "coinbase"
    capabilities = CollectorCapabilities(spot=True, historical_limit=300, supports_orderbook=True)

    def __init__(self, timeout: float = 20.0) -> None:
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(5)

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=COINBASE_BASE,
                timeout=self.timeout,
                headers={"User-Agent": "my-financ/0.1", "Accept": "application/json"},
                follow_redirects=False,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _get(self, path: str, params: dict | None = None) -> object:
        async with self._semaphore:
            client = await self._http()
            try:
                response = await client.get(path, params=params)
                if response.status_code in (400, 404):
                    raise SymbolNotSupportedError(f"Coinbase rejected {path}: {response.text[:200]}")
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                raise MarketDataError(f"Coinbase HTTP {exc.response.status_code} on {path}") from exc
            except httpx.HTTPError as exc:
                raise MarketDataError(f"Coinbase request failed on {path}: {exc}") from exc

    async def fetch_candles(
        self, symbol: str, timeframe: Timeframe = Timeframe.H1, limit: int = 300
    ) -> list[Candle]:
        limit = min(limit, self.capabilities.historical_limit)
        end = datetime.now(timezone.utc)
        start = end - timedelta(seconds=timeframe.seconds * limit)
        payload = await self._get(
            f"/products/{symbol}/candles",
            {
                "granularity": GRANULARITY[timeframe],
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )
        # Coinbase returns [time, low, high, open, close, volume], newest first.
        rows = [
            {
                "timestamp": entry[0],
                "low": entry[1],
                "high": entry[2],
                "open": entry[3],
                "close": entry[4],
                "volume": entry[5],
            }
            for entry in payload
        ]
        candles, _ = normalize_candles(rows, symbol=symbol, timeframe=timeframe, source=self.name)
        if not candles:
            raise MarketDataError(f"Coinbase returned no usable candles for {symbol}")
        if len(candles) > 1 and not self._is_closed(candles[-1], timeframe):
            candles = candles[:-1]
        return candles

    @staticmethod
    def _is_closed(candle: Candle, timeframe: Timeframe) -> bool:
        return datetime.now(timezone.utc) >= candle.timestamp + timedelta(seconds=timeframe.seconds)

    async def fetch_ticker(self, symbol: str) -> Ticker:
        payload = await self._get(f"/products/{symbol}/ticker")
        if not isinstance(payload, dict) or "price" not in payload:
            raise MarketDataError(f"Coinbase returned no ticker for {symbol}")
        price = float(payload["price"])
        return Ticker(symbol=symbol, last=price, volume_24h=payload.get("volume_24h"))