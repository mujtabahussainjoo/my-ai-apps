"""Domain enums shared across every layer.

These are plain ``str`` enums so they serialise cleanly to JSON for the API,
the dashboard, prompts, and the database.
"""

from __future__ import annotations

from enum import StrEnum


class TradingMode(StrEnum):
    """Execution environment. Ordered by increasing real-world risk."""

    BACKTEST = "backtest"
    PAPER = "paper"
    TESTNET = "testnet"
    LIVE = "live"

    @property
    def uses_real_money(self) -> bool:
        return self is TradingMode.LIVE

    @property
    def rank(self) -> int:
        """Higher means more dangerous. Used to enforce promotion order."""
        return {
            TradingMode.BACKTEST: 0,
            TradingMode.PAPER: 1,
            TradingMode.TESTNET: 2,
            TradingMode.LIVE: 3,
        }[self]


class SignalAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(StrEnum):
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class Timeframe(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"

    @property
    def seconds(self) -> int:
        return {
            Timeframe.M1: 60,
            Timeframe.M5: 300,
            Timeframe.M15: 900,
            Timeframe.H1: 3600,
            Timeframe.H4: 14_400,
            Timeframe.D1: 86_400,
        }[self]

    @property
    def binance_interval(self) -> str:
        return {
            Timeframe.M1: "1m",
            Timeframe.M5: "5m",
            Timeframe.M15: "15m",
            Timeframe.H1: "1h",
            Timeframe.H4: "4h",
            Timeframe.D1: "1d",
        }[self]


class MarketRegime(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    RANGE = "range"
    HIGH_VOLATILITY = "high_volatility"


class TrendState(StrEnum):
    STRONG_UP = "strong_up"
    UP = "up"
    NEUTRAL = "neutral"
    DOWN = "down"
    STRONG_DOWN = "strong_down"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


class RiskVerdict(StrEnum):
    APPROVED = "approved"
    APPROVED_REDUCED = "approved_reduced"
    REJECTED = "rejected"
    HALTED = "halted"


class RiskRule(StrEnum):
    """Identifiers for every guardrail check. Persisted on risk events."""

    KILL_SWITCH = "kill_switch"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    MAX_DRAWDOWN = "max_drawdown"
    MODE_NOT_ALLOWED = "mode_not_allowed"
    STRATEGY_NOT_QUALIFIED = "strategy_not_qualified"
    STALE_MARKET_DATA = "stale_market_data"
    INVALID_ORDER = "invalid_order"
    MISSING_STOP_LOSS = "missing_stop_loss"
    STOP_DISTANCE_OUT_OF_RANGE = "stop_distance_out_of_range"
    POOR_RISK_REWARD = "poor_risk_reward"
    MAX_POSITION_SIZE = "max_position_size"
    MAX_RISK_PER_TRADE = "max_risk_per_trade"
    MAX_TOTAL_EXPOSURE = "max_total_exposure"
    MAX_OPEN_POSITIONS = "max_open_positions"
    MAX_AI_TRADES_PER_DAY = "max_ai_trades_per_day"
    #: Marks an order that only reduces risk. Not a failure mode: it is
    #: recorded so the audit trail shows exits went through the engine too.
    POSITION_REDUCING = "position_reducing"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    MIN_ORDER_NOTIONAL = "min_order_notional"
    LEVERAGE_LIMIT = "leverage_limit"
    CORRELATION_LIMIT = "correlation_limit"
    EXISTING_SYMBOL_EXPOSURE = "existing_symbol_exposure"
    AGENT_NOT_APPROVED = "agent_not_approved"
    AGENT_OUTPUT_INVALID = "agent_output_invalid"
    APPROVAL_MISSING = "approval_missing"
    PROMPT_INJECTION_DETECTED = "prompt_injection_detected"
    LIVE_CONFIRMATION_MISSING = "live_confirmation_missing"


class AgentRole(StrEnum):
    SUPERVISOR = "supervisor"
    MARKET = "market"
    TECHNICAL = "technical"
    SENTIMENT = "sentiment"
    RISK = "risk"
    DECISION = "decision"


class AgentVerdict(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    ABSTAIN = "ABSTAIN"


class StrategyStatus(StrEnum):
    """Lifecycle of a strategy. Only QUALIFIED strategies may be traded."""

    CANDIDATE = "candidate"
    BACKTESTING = "backtesting"
    BACKTEST_PASSED = "backtest_passed"
    PAPER_TESTING = "paper_testing"
    QUALIFIED = "qualified"
    REJECTED = "rejected"
    RETIRED = "retired"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTED = "executed"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"