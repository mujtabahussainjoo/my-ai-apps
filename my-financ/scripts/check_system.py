"""Verify the system is wired up correctly, layer by layer.

Answers the question a new contributor actually has - "is this thing working?"
- without needing the API, a database or an OpenAI key, none of which exist yet.

    python -m scripts.check_system

Exits non-zero if any check fails, so it is usable as a CI gate or a
pre-flight check before `make api` / `make worker` are built.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from src.core.enums import OrderSide, SignalAction, Timeframe, TradingMode
from src.core.logging import configure_logging
from src.market_data.collectors.binance import SyntheticCollector


@dataclass
class Report:
    passed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    #: Things that are knowingly absent. Not failures - they are not built yet.
    notes: list[str] = field(default_factory=list)

    def ok(self, name: str, detail: str = "") -> None:
        self.passed.append(f"{name}{f' - {detail}' if detail else ''}")

    def bad(self, name: str, detail: str) -> None:
        self.failed.append((name, detail))

    def check(self, name: str, fn: Callable[[], str]) -> None:
        try:
            self.ok(name, fn())
        except Exception as exc:  # noqa: BLE001
            self.bad(name, f"{type(exc).__name__}: {exc}")


def check_config(r: Report) -> None:
    from src.core.config import get_settings

    s = get_settings()

    def defaults() -> str:
        assert s.trading_mode == TradingMode.PAPER, f"trading_mode is {s.trading_mode}"
        assert not s.live_trading_enabled, "live trading is ENABLED"
        assert not s.live_trading_i_understand_the_risk, "live risk ack is set"
        return f"mode={s.trading_mode}, live disabled"

    r.check("config loads with safe defaults", defaults)

    def secrets() -> str:
        key = s.openai_api_key.get_secret_value() if s.openai_api_key else ""
        assert not key or key.startswith("sk-"), "malformed key"
        return "live key present" if key else "no API key (agents cannot run yet)"

    r.check("secrets", secrets)


def check_kill_switch(r: Report) -> None:
    from src.core.security import kill_switch

    def engaged() -> str:
        kill_switch.engage("self-test")
        assert kill_switch.engaged, "kill switch did not engage"
        assert kill_switch.reason == "self-test", "reason not recorded"
        kill_switch.release(operator="self-test")
        assert not kill_switch.engaged, "kill switch did not release"
        return "engages and releases"

    r.check("kill switch", engaged)


def check_indicators(r: Report) -> None:
    import numpy as np
    from src.technical_analysis.feature_engine import (
        compute_features,
        compute_series_features,
    )

    async def candles() -> list:
        return await SyntheticCollector().fetch_historical(
            "BTC/USDT", Timeframe.H1, max_candles=300
        )

    def sane() -> str:
        bars = asyncio.run(candles())
        snap = compute_features(bars, timeframe="1h")
        assert snap.rsi is not None, "no RSI"
        assert 0 <= snap.rsi <= 100, f"RSI {snap.rsi} outside 0-100"
        assert snap.atr is not None and snap.atr > 0, "no usable ATR"
        assert snap.close > 0, "no close price"

        # Warmup NaN is correct (RSI needs 14 bars, MACD 25, EMA 49). NaN where
        # decisions are actually made is a bug that would reach a strategy.
        series = compute_series_features(bars)
        checked = 0
        for name, values in series.items():
            if not isinstance(values[0], (int, float)):
                continue  # 'timestamp' carries datetimes, not floats
            if name.startswith("swing_"):
                continue  # sparse by design: a value only at confirmed pivots
            arr = np.array(values, dtype=float)
            live = arr[max(0, arr.size - 100):]
            bad = np.isnan(live) | np.isinf(live)
            assert not bad.any(), (
                f"{name} has NaN/inf in the last 100 bars (indices "
                f"{np.where(bad)[0][:5].tolist()}...)"
            )
            checked += 1
        assert checked >= 15, f"only {checked} float series to check"
        assert snap.regime is not None, "no regime classification"
        return (
            f"{len(bars)} candles -> RSI {snap.rsi:.1f}, ATR {snap.atr:.2f}, "
            f"regime {snap.regime.value}; {checked} series clean in the live window"
        )

    r.check("indicators", sane)


def check_strategies(r: Report) -> None:
    from src.market_data.collectors.binance import SyntheticCollector
    from src.strategies.registry import all_names, evaluate_all
    from src.technical_analysis.feature_engine import compute_features

    async def candles() -> list:
        return await SyntheticCollector().fetch_historical(
            "BTC/USDT", Timeframe.H1, max_candles=800
        )

    def run() -> str:
        bars = asyncio.run(candles())
        snap = compute_features(bars, timeframe="1h")
        names = all_names()
        assert names, "no strategies registered"
        signals = evaluate_all("BTC/USDT", Timeframe.H1, bars, snap)
        for sig in signals:
            assert sig.action in (SignalAction.BUY, SignalAction.SELL)
            if sig.action == SignalAction.BUY:
                assert sig.stop_loss < sig.entry < sig.take_profit, (
                    f"long geometry wrong: stop={sig.stop_loss} entry={sig.entry} "
                    f"target={sig.take_profit}"
                )
            else:
                assert sig.take_profit < sig.entry < sig.stop_loss, (
                    f"short geometry wrong: target={sig.take_profit} entry={sig.entry} "
                    f"stop={sig.stop_loss}"
                )
        return f"{len(names)} strategies, {len(signals)} signals, geometry valid"

    r.check("strategies", run)


def check_risk_engine(r: Report) -> None:
    from src.risk.risk_engine import RiskEngine
    from src.schemas.order import OrderRequest
    from src.schemas.portfolio import PortfolioSnapshot

    portfolio = PortfolioSnapshot(equity_usd=10000.0, cash_usd=10000.0)

    def rejects_missing_stop() -> str:
        a = RiskEngine().assess(
            OrderRequest(symbol="BTC/USDT", side=OrderSide.BUY, quantity=Decimal("0.01")),
            portfolio,
        )
        assert not a.allowed, "an order with no stop loss was allowed"
        return f"no-stop order -> {a.verdict.value}"

    def approves_good_order() -> str:
        from src.schemas.market import Ticker

        # A BUY is priced at the ask (100001), not at 'last', so the stop is
        # sized from the ask. Sizing it off 'last' lands at 5.0004% and is
        # correctly refused as too wide.
        a = RiskEngine().assess(
            OrderRequest(
                symbol="BTC/USDT",
                side=OrderSide.BUY,
                quantity=Decimal("0.01"),
                stop_loss=Decimal("95100"),
                take_profit=Decimal("110000"),
                strategy="breakout",
            ),
            portfolio,
            ticker=Ticker(symbol="BTC/USDT", last=Decimal("100000"),
                          bid=Decimal("99999"), ask=Decimal("100001")),
        )
        assert a.allowed, f"good order rejected: {a.reasons}"
        return f"valid order -> {a.verdict.value} qty={a.approved_quantity}"

    def ask_spread_counts_toward_stop_width() -> str:
        """A stop sized off the last price can breach the distance limit."""
        from src.schemas.market import Ticker

        a = RiskEngine().assess(
            OrderRequest(
                symbol="BTC/USDT",
                side=OrderSide.BUY,
                quantity=Decimal("0.01"),
                stop_loss=Decimal("95000"),  # exactly 5% below 'last'...
                take_profit=Decimal("110000"),
                strategy="breakout",
            ),
            portfolio,
            ticker=Ticker(symbol="BTC/USDT", last=Decimal("100000"),
                          bid=Decimal("99999"), ask=Decimal("100001")),
        )  # ...but >5% below the ask it is actually filled at.
        assert not a.allowed, "an over-wide stop was approved"
        return "stop width is measured from the fill price, not the last price"

    def live_is_gated() -> str:
        from src.core.config import Settings
        from src.schemas.market import Ticker

        engine = RiskEngine(Settings(trading_mode="live", live_trading_enabled=True))
        a = engine.assess(
            OrderRequest(
                symbol="BTC/USDT",
                side=OrderSide.BUY,
                quantity=Decimal("0.01"),
                stop_loss=Decimal("95000"),
                take_profit=Decimal("112000"),
                strategy="breakout",
            ),
            portfolio,
            ticker=Ticker(symbol="BTC/USDT", last=Decimal("100000"),
                          bid=Decimal("99999"), ask=Decimal("100001")),
        )
        assert a.verdict.value != "approved", "live order approved without human approval"
        return f"live order -> {a.verdict.value}"

    r.check("risk: mandatory stop", rejects_missing_stop)
    r.check("risk: approves valid order", approves_good_order)
    r.check("risk: stop width from fill price", ask_spread_counts_toward_stop_width)
    r.check("risk: live requires approval", live_is_gated)


def check_backtest(r: Report) -> None:
    from src.backtesting.engine import BacktestConfig, BacktestEngine
    from src.market_data.collectors.binance import SyntheticCollector

    def reconciles() -> str:
        async def bars() -> list:
            return await SyntheticCollector().fetch_historical(
                "BTC/USDT", Timeframe.H1, max_candles=1500
            )

        candles = asyncio.run(bars())
        result = BacktestEngine().run(
            candles, BacktestConfig(strategy="breakout", symbol="BTC/USDT", timeframe=Timeframe.H1)
        )
        assert result.trades, "no trades generated"
        total = sum(t.pnl_usd for t in result.trades)
        assert abs(total - result.metrics.net_profit_usd) < 1e-6, "trade log != metrics"
        assert abs(result.equity_curve[-1] - (10000 + total)) < 1e-6, "curve != trade log"
        for t in result.trades:
            assert abs(t.pnl_usd - (t.gross_pnl_usd - t.fees_usd)) < 1e-6, "fee mismatch"
        return f"{len(result.trades)} trades, P&L reconciles across all three views"

    r.check("backtest accounting", reconciles)


def check_persistence(r: Report) -> None:
    """Prove the schema is really applied, not merely importable."""
    import sqlalchemy as sa

    # Importing the models package is what registers the mappers on Base;
    # without it Base.metadata is empty and this check proves nothing.
    import src.database.models  # noqa: F401
    from src.database.base import Base
    from src.database.migrations import applied_versions, discover, pending
    from src.database.session import build_engine

    try:
        engine = build_engine()
        with engine.connect() as conn:
            conn.execute(sa.text("select 1"))
    except Exception as exc:
        r.bad(
            "database reachable",
            f"{type(exc).__name__}: {str(exc).splitlines()[0][:120]} (run 'make up')",
        )
        return

    try:
        with engine.connect() as conn:
            actual = set(
                conn.execute(
                    sa.text(
                        "select table_name from information_schema.tables "
                        "where table_schema = 'public' and table_type = 'BASE TABLE'"
                    )
                ).scalars()
            )
    except Exception as exc:
        r.bad("database tables readable", f"{type(exc).__name__}: {exc}")
        return

    expected = set(Base.metadata.tables)
    missing = expected - actual
    if missing:
        r.bad("schema applied", f"missing {len(missing)} table(s): {sorted(missing)[:5]}")
        return

    applied = applied_versions(engine)
    outstanding = [m.version for m in pending(engine)]
    if outstanding:
        r.bad("schema applied", f"unapplied migrations: {outstanding} (run 'make migrate')")
        return

    total = len(discover())
    r.ok(
        "persistence",
        f"{len(actual)} tables incl. {len(expected)} mapped, "
        f"{len(applied)}/{total} migrations applied, no drift",
    )


def check_agents_and_db(r: Report) -> None:
    """Report what is not built yet, rather than pretending it is."""

    from pathlib import Path

    def has_files(path: str) -> bool:
        """An empty package is just a placeholder - ``__init__.py`` alone is not code."""
        p = Path(path)
        if not p.exists():
            return False
        return any(
            f.is_file() and f.suffix != ".pyc" and f.name != "__init__.py"
            for f in p.rglob("*")
        )

    missing = [
        name
        for name, path in (
            ("SQLAlchemy models", "src/database/models"),
            ("OpenAI agents", "src/agents"),
            ("executors", "src/trading/executor.py"),
            ("FastAPI app", "apps/api/main.py"),
            ("worker", "apps/worker/main.py"),
            ("dashboard", "apps/dashboard/package.json"),
            ("Dockerfiles", "infrastructure/docker"),
        )
        if not has_files(path)
    ]
    if missing:
        r.notes.append(f"not built yet: {', '.join(missing)}")
    else:
        r.ok("pipeline layers", "all present")


def _t(i: int):
    from datetime import datetime, timedelta, timezone

    return datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i)


def main() -> int:
    configure_logging()
    r = Report()
    for fn in (
        check_config,
        check_kill_switch,
        check_indicators,
        check_strategies,
        check_risk_engine,
        check_backtest,
        check_persistence,
        check_agents_and_db,
    ):
        fn(r)

    for line in r.passed:
        print(f"  PASS  {line}")
    for name, detail in r.failed:
        print(f"  FAIL  {name} - {detail}")
    for line in r.notes:
        print(f"  TODO  {line}")

    total = len(r.passed) + len(r.failed)
    print(f"\n{len(r.passed)}/{total} checks passed")
    if not r.failed:
        print("core pipeline healthy")
    return 1 if r.failed else 0


if __name__ == "__main__":
    sys.exit(main())