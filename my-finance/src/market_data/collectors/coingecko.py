"""CoinGecko collector — supplementary metadata and market-wide context.

Never used as a price source for trading decisions: CoinGecko's free tier is
rate-limited and its prices lag the exchanges. It supplies market cap,
dominance-style context and 24h change for the sentiment agent.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from src.core.config import Settings, get_settings
from src.core.enums import Timeframe
from src.core.exceptions import MarketDataError
from src.core.logging import get_logger
from src.market_data.models import BaseCollector, CollectorCapabilities
from src.schemas.market import Candle, CoinMetadata, MarketContext, Ticker

logger = get_logger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

#: Unified symbol -> CoinGecko id.
COIN_IDS: dict[str, str] = {
    "BTC/USDT": "bitcoin",
    "ETH/USDT": "ethereum",
    "SOL/USDT": "solana",
    "BNB/USDT": "binancecoin",
    "XRP/USDT": "ripple",
    "ADA/USDT": "cardano",
    "DOGE/USDT": "dogecoin",
    "AVAX/USDT": "avalanche-2",
    "LINK/USDT": "chainlink",
    "DOT/USDT": "polkadot",
    "MATIC/USDT": "matic-network",
    "LTC/USDT": "litecoin",
    "ATOM/USDT": "cosmos",
    "UNI/USDT": "uniswap",
    "NEAR/USDT": "near",
    "APT/USDT": "aptos",
    "ARB/USDT": "arbitrum",
    "OP/USDT": "optimism",
    "SUI/USDT": "sui",
    "FIL/USDT": "filecoin",
    "TRX/USDT": "tron",
}


def base_asset(symbol: str) -> str:
    return symbol.split("/")[0].upper()


class CoinGeckoCollector(BaseCollector):
    name = "coingecko"
    capabilities = CollectorCapabilities(spot=True, historical_limit=365)

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(2)
        self._cache: dict[str, CoinMetadata] = {}
        self._cache_ttl = 300.0
        self._fetched_at: dict[str, float] = {}

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=COINGECKO_BASE,
                timeout=self.settings.market_data_timeout_seconds,
                headers={"Accept": "application/json", "User-Agent": "my-financ/0.1"},
                follow_redirects=False,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        async with self._semaphore:
            client = await self._http()
            try:
                response = await client.get(path, params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    raise MarketDataError("CoinGecko rate limit reached") from exc
                raise MarketDataError(f"CoinGecko HTTP {exc.response.status_code} on {path}") from exc
            except httpx.HTTPError as exc:
                raise MarketDataError(f"CoinGecko request failed on {path}: {exc}") from exc

    async def fetch_metadata(self, symbol: str) -> CoinMetadata | None:
        """Fetch and cache coin metadata. Returns None on any failure."""
        import time

        coin_id = COIN_IDS.get(symbol)
        if coin_id is None:
            return None
        cached = self._cache.get(symbol)
        if cached is not None and time.time() - self._fetched_at.get(symbol, 0) < self._cache_ttl:
            return cached
        try:
            payload = await self._get(
                "/coins/markets",
                {"vs_currency": "usd", "ids": coin_id, "price_change_percentage": "24h"},
            )
            if not payload:
                return None
            entry = payload[0]
            metadata = CoinMetadata(
                symbol=symbol,
                name=entry.get("name", base_asset(symbol)),
                market_cap=entry.get("market_cap"),
                market_cap_rank=entry.get("market_cap_rank"),
                total_volume=entry.get("total_volume"),
                price_change_percentage_24h=entry.get("price_change_percentage_24h"),
                circulating_supply=entry.get("circulating_supply"),
                ath=entry.get("ath"),
                ath_change_percentage=entry.get("ath_change_percentage"),
            )
            self._cache[symbol] = metadata
            self._fetched_at[symbol] = time.time()
            return metadata
        except MarketDataError as exc:
            logger.warning("coingecko_metadata_failed", symbol=symbol, error=str(exc))
            return None

    async def fetch_global_context(self) -> MarketContext:
        """Market-wide stats used for regime detection and sentiment."""
        try:
            payload = await self._get("/global")
            data = payload.get("data", {})
            total_market_cap = (data.get("total_market_cap") or {}).get("usd")
            dominance = (data.get("market_cap_percentage") or {}).get("btc")
            change = data.get("market_cap_change_percentage_24h_usd")
            notes: list[str] = []
            if change is not None:
                notes.append(f"total crypto market cap moved {change:+.2f}% in 24h")
            return MarketContext(
                btc_dominance=round(dominance, 2) if dominance is not None else None,
                total_market_cap_usd=total_market_cap,
                notes=notes,
            )
        except MarketDataError as exc:
            logger.warning("coingecko_global_failed", error=str(exc))
            return MarketContext()

    async def fetch_ticker(self, symbol: str) -> Ticker:
        """Price from CoinGecko — for display only, not for order pricing."""
        coin_id = COIN_IDS.get(symbol)
        if coin_id is None:
            raise MarketDataError(f"no CoinGecko id for {symbol}")
        payload = await self._get("/simple/price", {"ids": coin_id, "vs_currencies": "usd"})
        price = (payload.get(coin_id) or {}).get("usd")
        if price is None:
            raise MarketDataError(f"CoinGecko returned no price for {symbol}")
        return Ticker(symbol=symbol, last=float(price))

    async def fetch_candles(
        self, symbol: str, timeframe: Timeframe = Timeframe.H1, limit: int = 500
    ) -> list[Candle]:
        raise MarketDataError(
            "CoinGecko is metadata-only in this system; use an exchange collector "
            "for candles so prices match the execution venue."
        )
