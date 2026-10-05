"""Collector registry with graceful degradation.

Resolution order is explicit and logged: a silent fallback from live data to
synthetic data would be a safety problem, because the system could then size
positions from a random walk while claiming to be trading the real market.
"""

from __future__ import annotations

from src.core.config import Settings, get_settings
from src.core.exceptions import MarketDataError
from src.core.logging import get_logger
from src.market_data.collectors.binance import BinanceCollector, SyntheticCollector
from src.market_data.collectors.coinbase import CoinbaseCollector
from src.market_data.collectors.coingecko import CoinGeckoCollector
from src.market_data.models import BaseCollector

logger = get_logger(__name__)


def build_collector(exchange: str, settings: Settings | None = None) -> BaseCollector:
    """Instantiate a collector by exchange id."""
    settings = settings or get_settings()
    match exchange.lower():
        case "binance":
            return BinanceCollector(settings)
        case "coinbase":
            return CoinbaseCollector(settings.market_data_timeout_seconds)
        case "synthetic":
            return SyntheticCollector(settings=settings)
        case _:
            raise MarketDataError(
                f"unknown exchange '{exchange}'. Supported: binance, coinbase, synthetic"
            )


class CollectorRegistry:
    """Caches collector instances and exposes the auxiliary sources.

    ``allow_synthetic_fallback`` is opt-in per call. Callers trading in a live
    mode must leave it False so a network outage surfaces as an error instead
    of fabricated candles.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._collectors: dict[str, BaseCollector] = {}
        self.coingecko = CoinGeckoCollector(self.settings)

    def get(self, exchange: str | None = None) -> BaseCollector:
        name = (exchange or self.settings.exchange_id).lower()
        if name not in self._collectors:
            self._collectors[name] = build_collector(name, self.settings)
        return self._collectors[name]

    def synthetic(self) -> SyntheticCollector:
        collector = self._collectors.get("synthetic")
        if not isinstance(collector, SyntheticCollector):
            collector = SyntheticCollector(settings=self.settings)
            self._collectors["synthetic"] = collector
        return collector

    async def get_with_fallback(self, exchange: str | None = None) -> BaseCollector:
        """Return the real collector, falling back to synthetic only if allowed."""
        collector = self.get(exchange)
        if not self.settings.market_data_allow_synthetic:
            return collector
        # Probe cheaply: if the primary is unreachable, say so loudly.
        try:
            await collector.fetch_ticker("BTC/USDT")
            return collector
        except MarketDataError as exc:
            logger.warning(
                "market_data_degraded",
                exchange=collector.name,
                error=str(exc),
                action="falling_back_to_synthetic",
                warning="Synthetic data is NOT tradable. Backtest/demo only.",
            )
            return self.synthetic()

    async def close(self) -> None:
        for collector in self._collectors.values():
            await collector.close()
        await self.coingecko.close()
        self._collectors.clear()


_registry: CollectorRegistry | None = None


def get_registry() -> CollectorRegistry:
    global _registry
    if _registry is None:
        _registry = CollectorRegistry()
    return _registry


async def close_registry() -> None:
    global _registry
    if _registry is not None:
        await _registry.close()
        _registry = None