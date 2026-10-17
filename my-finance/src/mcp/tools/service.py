"""Narrow agent tools. Every order tool is paper-only and risk-gated."""

from src.core.enums import Timeframe, TradingMode
from src.database.repositories import (
    CandleRepository,
    PortfolioRepository,
    SignalRepository,
    TradeRepository,
)
from src.evaluation.service import evaluate_strategy
from src.technical_analysis.feature_engine import compute_features


class Tools:
    def __init__(self, session, settings):
        self.session, self.settings = session, settings

    def get_price(self, symbol: str):
        candles = CandleRepository(self.session).latest(symbol, Timeframe(self.settings.trading_timeframe))
        if not candles:
            raise ValueError("No stored market price; download history first")
        candle = candles[0]
        return {
            "symbol": symbol,
            "price": candle.close,
            "timestamp": candle.timestamp.isoformat(),
            "source": "stored candle close",
            "live_quote": False,
        }

    def get_ohlcv(self, symbol: str, timeframe: str = "1h", limit: int = 200):
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be 1–1000")
        candles = CandleRepository(self.session).get_range(
            symbol, Timeframe(timeframe), limit=limit, ascending=False
        )
        return [c.model_dump(mode="json") for c in reversed(candles)]

    def calculate_indicators(self, symbol: str, timeframe: str = "1h"):
        candles = CandleRepository(self.session).get_range(
            symbol, Timeframe(timeframe), limit=300, ascending=False
        )
        return compute_features(list(reversed(candles)), timeframe=timeframe).model_dump(mode="json")

    def get_portfolio(self):
        return (
            PortfolioRepository(self.session)
            .build_snapshot(self.settings.trading_mode)
            .model_dump(mode="json")
        )

    def get_open_positions(self):
        return [
            p.model_dump(mode="json")
            for p in PortfolioRepository(self.session).get_positions(self.settings.trading_mode)
        ]

    def get_strategy_metrics(self, strategy: str):
        result, ready, evidence = evaluate_strategy(self.session, strategy, self.settings)
        return {"qualification": result.model_dump(mode="json"), "paper_ready": ready, "evidence": evidence}

    def calculate_position_size(self, entry: float, stop_loss: float):
        portfolio = PortfolioRepository(self.session).build_snapshot(self.settings.trading_mode)
        from math import isfinite

        if (
            not isfinite(entry)
            or not isfinite(stop_loss)
            or entry <= 0
            or stop_loss <= 0
            or entry == stop_loss
        ):
            raise ValueError("Invalid entry or stop")
        risk_budget = portfolio.equity_usd * self.settings.risk_max_risk_per_trade_pct / 100
        quantity = min(
            risk_budget / abs(entry - stop_loss),
            portfolio.equity_usd * self.settings.risk_max_position_pct / 100 / entry,
        )
        return {
            "quantity": quantity,
            "notional_usd": quantity * entry,
            "risk_usd": quantity * abs(entry - stop_loss),
            "requires_risk_assessment": True,
        }

    def run_backtest(self, strategy: str, symbol: str, timeframe: str = "1h", limit: int = 1500):
        from src.backtesting.engine import BacktestConfig, BacktestEngine

        if not 300 <= limit <= 5000:
            raise ValueError("limit must be 300–5000")
        candles = CandleRepository(self.session).get_range(
            symbol, Timeframe(timeframe), limit=limit, ascending=False
        )
        result = BacktestEngine(self.settings).run(
            list(reversed(candles)),
            BacktestConfig(strategy=strategy, symbol=symbol, timeframe=Timeframe(timeframe)),
        )
        return result.to_dict()

    def get_paper_pnl(self):
        return {
            "realized_pnl_usd": TradeRepository(self.session).realized_pnl(mode="paper"),
            "portfolio": PortfolioRepository(self.session).build_snapshot("paper").model_dump(mode="json"),
        }

    def create_paper_order(self, signal_id: str):
        if not self.settings.mcp_allow_order_tools or self.settings.trading_mode != "paper":
            raise PermissionError("MCP order tools require explicit enablement and paper mode")
        from src.trading.signal_processor import build_signal_processor

        signal = SignalRepository(self.session).get(signal_id)
        if signal is None:
            raise ValueError("Signal not found")
        processor = build_signal_processor(self.session, self.settings, mode=TradingMode.PAPER)
        try:
            return vars(processor.handle(signal))
        finally:
            processor.quotes.close()
