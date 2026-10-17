"""Download genuine market history to the configured candle repository."""

import argparse
import asyncio

from src.core.config import get_settings
from src.core.enums import Timeframe
from src.database.repositories import CandleRepository
from src.database.session import session_scope
from src.market_data.normalization import CollectorRegistry


async def download(settings, *, bars=1500, source=None):
    registry = CollectorRegistry(settings)
    collected = []
    try:
        collector = registry.get(source)
        for symbol in settings.trading_symbols:
            collected.extend(
                await collector.fetch_historical(
                    symbol, Timeframe(settings.trading_timeframe), max_candles=bars
                )
            )
        return collected
    finally:
        await registry.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=int, default=1500)
    parser.add_argument("--source", choices=["binance", "coinbase"], default=None)
    args = parser.parse_args(argv)
    if not 300 <= args.bars <= 50000:
        parser.error("bars must be between 300 and 50000")
    settings = get_settings()
    candles = asyncio.run(download(settings, bars=args.bars, source=args.source))
    if not candles:
        raise SystemExit("No history returned")
    with session_scope() as session:
        count = CandleRepository(session).upsert_many(candles)
    print(f"Stored {count} candles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
