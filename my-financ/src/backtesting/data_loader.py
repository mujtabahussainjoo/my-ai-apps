"""Historical data loading with on-disk caching.

Backtests must be reproducible, so downloaded candles are cached to parquet and
reused. The cache is keyed on symbol/timeframe/limit so a changed request
cannot silently return stale rows.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.core.config import Settings, get_settings
from src.core.enums import Timeframe
from src.core.exceptions import MarketDataError
from src.core.logging import get_logger
from src.market_data.normalization import get_registry
from src.schemas.market import Candle

logger = get_logger(__name__)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class HistoricalDataLoader:
    """Loads candles from cache or the network."""

    def __init__(self, settings: Settings | None = None, cache_dir: Path | None = None) -> None:
        self.settings = settings or get_settings()
        self.cache_dir = cache_dir or (DATA_DIR / "historical")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, symbol: str, timeframe: Timeframe, limit: int, source: str) -> Path:
        key = hashlib.sha256(f"{symbol}:{timeframe.value}:{limit}:{source}".encode()).hexdigest()[:16]
        safe_symbol = symbol.replace("/", "-")
        return self.cache_dir / f"{safe_symbol}_{timeframe.value}_{limit}_{key}.parquet"

    def read_cache(self, path: Path) -> list[Candle]:
        try:
            import pandas as pd

            frame = pd.read_parquet(path)
            return [
                Candle(
                    timestamp=row["timestamp"],
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["volume"]),
                    symbol=row.get("symbol", "BTC/USDT"),
                    timeframe=row.get("timeframe", Timeframe.H1),
                )
                for row in frame.to_dict("records")
            ]
        except Exception as exc:  # noqa: BLE001 - a bad cache must not be fatal
            logger.warning("cache_read_failed", path=str(path), error=str(exc))
            return []

    def _write_cache(self, path: Path, candles: list[Candle]) -> None:
        try:
            import pandas as pd

            frame = pd.DataFrame(
                [
                    {
                        "timestamp": c.timestamp,
                        "open": c.open,
                        "high": c.high,
                        "low": c.low,
                        "close": c.close,
                        "volume": c.volume,
                        "symbol": c.symbol,
                        "timeframe": c.timeframe.value,
                    }
                    for c in candles
                ]
            )
            frame.to_parquet(path, index=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache_write_failed", path=str(path), error=str(exc))

    async def load(
        self,
        symbol: str,
        timeframe: Timeframe = Timeframe.H1,
        limit: int = 1000,
        *,
        use_cache: bool = True,
        source: str = "binance",
    ) -> list[Candle]:
        """Return candles, preferring the on-disk cache."""
        path = self._cache_path(symbol, timeframe, limit, source)
        if use_cache and path.exists():
            cached = self.read_cache(path)
            if cached:
                logger.info("cache_hit", symbol=symbol, path=str(path), candles=len(cached))
                return cached

        collector = get_registry().get(source)
        fetch_history = getattr(collector, "fetch_historical", None)
        if callable(fetch_history):
            candles = await fetch_history(symbol, timeframe, max_candles=limit)
        else:
            candles = await collector.fetch_candles(symbol, timeframe, limit)

        if not candles:
            raise MarketDataError(f"no candles available for {symbol} from {source}")

        if use_cache:
            self._write_cache(path, candles)
        return candles

    async def load_multi(
        self,
        symbols: list[str],
        timeframe: Timeframe = Timeframe.H1,
        limit: int = 1000,
        *,
        source: str = "binance",
    ) -> dict[str, list[Candle]]:
        import asyncio

        results = await asyncio.gather(
            *(self.load(symbol, timeframe, limit, source=source) for symbol in symbols),
            return_exceptions=True,
        )
        out: dict[str, list[Candle]] = {}
        for symbol, result in zip(symbols, results, strict=True):
            if isinstance(result, Exception):
                logger.warning("history_load_failed", symbol=symbol, error=str(result))
                continue
            out[symbol] = result
        if not out:
            raise MarketDataError(f"failed to load history for any of {symbols}")
        return out

    def load_synthetic(
        self,
        symbol: str,
        timeframe: Timeframe = Timeframe.H1,
        limit: int = 1000,
    ) -> list[Candle]:
        """Synchronous synthetic load for tests and offline runs."""
        from src.market_data.collectors.binance import SyntheticCollector

        return SyntheticCollector()._generate(symbol, timeframe, limit)  # noqa: SLF001

    def clear_cache(self) -> int:
        removed = 0
        for path in self.cache_dir.glob("*.parquet"):
            path.unlink()
            removed += 1
        return removed


def split_by_date(
    candles: list[Candle], fraction: float = 0.7
) -> tuple[list[Candle], list[Candle]]:
    """Chronological split for in-sample / out-of-sample separation."""
    if not candles:
        return [], []
    cutoff_index = max(1, int(len(candles) * fraction))
    return candles[:cutoff_index], candles[cutoff_index:]


def data_quality(candles: list[Candle]) -> dict[str, object]:
    """Gap and duplicate audit — run before trusting any backtest."""
    if not candles:
        return {"candles": 0, "issues": ["empty series"]}

    ordered = sorted(candles, key=lambda c: c.timestamp)
    gaps: list[float] = []
    for previous, current in zip(ordered, ordered[1:], strict=False):
        delta = (current.timestamp - previous.timestamp).total_seconds()
        if delta > 0:
            gaps.append(delta)

    issues: list[str] = []
    duplicates = 0
    seen: set[int] = set()
    for candle in ordered:
        key = int(candle.timestamp.timestamp())
        if key in seen:
            duplicates += 1
        seen.add(key)

    if gaps:
        median = sorted(gaps)[len(gaps) // 2]
        outliers = [g for g in gaps if median > 0 and g > median * 3]
        if outliers:
            issues.append(
                f"{len(outliers)} gaps exceed 3x the median interval "
                f"({median:.0f}s); the largest is {max(outliers) / 3600:.1f}h"
            )
    if duplicates:
        issues.append(f"{duplicates} duplicate timestamps")

    return {
        "candles": len(ordered),
        "from": ordered[0].timestamp.isoformat(),
        "to": ordered[-1].timestamp.isoformat(),
        "duplicates": duplicates,
        "max_gap_hours": round(max(gaps) / 3600, 2) if gaps else 0.0,
        "issues": issues,
        "usable": not issues or duplicates == 0,
    }


def persist_candles(candles: list[Candle], name: str) -> Path:
    """Explicitly save a series to ``data/historical``."""
    directory = DATA_DIR / "historical"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.parquet"
    try:
        import pandas as pd

        pd.DataFrame(
            [
                {
                    "timestamp": c.timestamp,
                    "open": c.open,
                    "high": c.high,
                    "low": c.low,
                    "close": c.close,
                    "volume": c.volume,
                    "symbol": c.symbol,
                    "timeframe": c.timeframe.value,
                }
                for c in candles
            ]
        ).to_parquet(path, index=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("persist_failed", path=str(path), error=str(exc))
    return path


def load_persisted(name: str) -> list[Candle]:
    path = DATA_DIR / "historical" / f"{name}.parquet"
    loader = HistoricalDataLoader()
    return loader.read_cache(path)