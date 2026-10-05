"""Run the deterministic pipeline end to end from the command line.

This is the only runnable entry point today: market data -> indicators ->
strategies -> hard risk -> backtest. No database, API or agent is required,
because none of them are allowed to influence what happens here.

    python -m scripts.run_backtest --strategy breakout --source binance --timeframe 4h
    python -m scripts.run_backtest --all --source synthetic --bars 2000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from src.backtesting.engine import BacktestConfig, BacktestEngine, BacktestResult
from src.core.enums import Timeframe
from src.core.logging import configure_logging
from src.market_data.collectors.binance import BinanceCollector, SyntheticCollector
from src.strategies.registry import all_names


async def fetch_candles(source: str, symbol: str, timeframe: Timeframe, bars: int) -> list:
    """Fetch the candle history a backtest needs.

    ``bars`` may exceed a single exchange request, so pagination happens here
    rather than being assumed.
    """
    if source == "synthetic":
        collector = SyntheticCollector()
        return await collector.fetch_historical(symbol, timeframe, max_candles=bars)

    collector = BinanceCollector()
    try:
        return await collector.fetch_historical(symbol, timeframe, max_candles=bars)
    finally:
        await collector.close()


def run_one(strategy: str, candles: list, symbol: str, timeframe: Timeframe) -> BacktestResult:
    config = BacktestConfig(strategy=strategy, symbol=symbol, timeframe=timeframe)
    return BacktestEngine().run(candles, config)


def report(result: BacktestResult) -> None:
    m = result.metrics
    print(f"\n  {m.total_trades} trades  |  signals: {result.signals_generated}")
    print(f"  win rate      {m.win_rate:>8.1%}   ({m.winning_trades}W/{m.losing_trades}L)")
    print(f"  net profit    {m.net_profit_usd:>+8.2f} {result.config.starting_equity and 'USD'} "
          f"({m.net_profit_pct:+.2f}%)")
    print(f"  profit factor {m.profit_factor:>8.2f}")
    print(f"  max drawdown  {m.max_drawdown_pct:>8.2f}%")
    print(f"  expectancy    {m.expectancy_usd:>+8.2f} USD/trade  ({m.expectancy_r:+.3f}R)")
    print(f"  total fees    {m.total_fees_usd:>8.2f}")
    print(f"  equity        {result.equity_curve[0]:,.2f} -> {result.equity_curve[-1]:,.2f}")


def reconcile(result: BacktestResult) -> None:
    """Three independent views of one number must agree.

    Cash, the trade log and the metrics are computed separately. A disagreement
    means a P&L is being counted twice, so this is a hard failure rather than
    a warning.
    """
    total = sum(t.pnl_usd for t in result.trades)
    if abs(total - result.metrics.net_profit_usd) > 1e-6:
        raise SystemExit(
            f"accounting error: trades sum to {total:.6f} but metrics report "
            f"{result.metrics.net_profit_usd:.6f}"
        )
    final = result.config.starting_equity + total
    if abs(result.equity_curve[-1] - final) > 1e-6:
        raise SystemExit(
            f"accounting error: equity curve ends at {result.equity_curve[-1]:.6f}, "
            f"expected {final:.6f}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", default="breakout", help=f"one of: {', '.join(all_names())}")
    parser.add_argument("--all", action="store_true", help="run every registered strategy")
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--timeframe", default="1h", choices=[t.value for t in Timeframe])
    parser.add_argument("--source", default="synthetic", choices=["binance", "synthetic"])
    parser.add_argument("--bars", type=int, default=1500)
    parser.add_argument("--json", action="store_true", help="emit raw JSON")
    args = parser.parse_args(argv)

    configure_logging()
    timeframe = Timeframe(args.timeframe)
    strategies = all_names() if args.all else [args.strategy]
    unknown = [s for s in strategies if s not in all_names()]
    if unknown:
        parser.error(f"unknown strategy: {unknown[0]}; choose from {all_names()}")

    try:
        candles = asyncio.run(fetch_candles(args.source, args.symbol, timeframe, args.bars))
    except Exception as exc:  # noqa: BLE001
        print(f"could not fetch {args.symbol} from {args.source}: {exc}", file=sys.stderr)
        return 1

    if not candles:
        print(f"no candles returned for {args.symbol}", file=sys.stderr)
        return 1

    span = candles[-1].timestamp - candles[0].timestamp
    print(f"{len(candles)} {timeframe.value} candles  {span.days}d  "
          f"{candles[0].timestamp:%Y-%m-%d} -> {candles[-1].timestamp:%Y-%m-%d}  "
          f"[{args.source}]")

    results = []
    for name in strategies:
        result = run_one(name, candles, args.symbol, timeframe)
        reconcile(result)
        results.append(result)
        if not args.json:
            print(f"\n=== {name} ===")
            report(result)

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2, default=str))

    # A strategy with no trades is a configuration problem, not a result.
    quiet = [r.config.strategy for r in results if r.metrics.total_trades == 0]
    if quiet:
        print(f"\nwarning: no trades for {quiet} - check warmup or thresholds", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())