"""Constants shared across layers."""

from __future__ import annotations

from typing import Final

# ── Universe ────────────────────────────────────────────────────────────────
DEFAULT_SYMBOLS: Final[tuple[str, ...]] = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
DEFAULT_TIMEFRAME: Final[str] = "1h"
SUPPORTED_EXCHANGES: Final[tuple[str, ...]] = ("binance", "coinbase", "kraken")

# ── Data freshness ──────────────────────────────────────────────────────────
#: A quote older than this is stale and the risk engine rejects trades on it.
MAX_QUOTE_AGE_SECONDS: Final[int] = 120
#: Candles are allowed more lag than live quotes.
MAX_CANDLE_AGE_SECONDS: Final[int] = 900
#: Refuse to build a backtest on less than this many candles.
MIN_CANDLES_FOR_BACKTEST: Final[int] = 300

# ── Indicator defaults ──────────────────────────────────────────────────────
#: Swing-confirmation width. A pivot found at bar ``j`` is only knowable at
#: ``j + PIVOT_RIGHT``, so anything reading pivot levels must lag by this much
#: or it will peek at future bars.
PIVOT_LEFT: Final[int] = 3
PIVOT_RIGHT: Final[int] = 3
RSI_PERIOD: Final[int] = 14
RSI_OVERSOLD: Final[float] = 30.0
RSI_OVERBOUGHT: Final[float] = 70.0
EMA_FAST: Final[int] = 20
EMA_SLOW: Final[int] = 50
MACD_FAST: Final[int] = 12
MACD_SLOW: Final[int] = 26
MACD_SIGNAL: Final[int] = 9
BOLLINGER_PERIOD: Final[int] = 20
BOLLINGER_STD: Final[float] = 2.0
ATR_PERIOD: Final[int] = 14
ADX_PERIOD: Final[int] = 14
VOLUME_MA_PERIOD: Final[int] = 20

# ── Sizing / execution ──────────────────────────────────────────────────────
MIN_ORDER_NOTIONAL_USD: Final[float] = 10.0
PRICE_QUANTITY_DECIMALS: Final[int] = 8
#: Hard cap on notional for a single order, independent of portfolio size.
MAX_ORDER_NOTIONAL_USD: Final[float] = 50_000.0

# ── Live approvals ──────────────────────────────────────────────────────────
#: A human approval expires quickly so it cannot be reused later for a
#: different market state.
APPROVAL_TTL_SECONDS: Final[int] = 120
#: Live orders must never use market orders at market price without bounds.
LIVE_ORDER_SLIPPAGE_TOLERANCE_BPS: Final[float] = 100.0

# ── Risk scoring weights (Workflow.md §21) ─────────────────────────────────
SIGNAL_SCORE_WEIGHTS: Final[dict[str, float]] = {
    "technical": 0.30,
    "trend": 0.20,
    "volume": 0.15,
    "market_regime": 0.15,
    "sentiment": 0.10,
    "risk": 0.10,
}
#: A candidate below this signal score is dropped before the LLM even runs.
MIN_SIGNAL_SCORE_TO_ANALYSE: Final[float] = 55.0
#: Minimum score for the agent stage to be able to approve.
MIN_SIGNAL_SCORE_TO_TRADE: Final[float] = 65.0

# ── Agent orchestration ─────────────────────────────────────────────────────
#: Subagent weights for the decision agent's confidence computation.
AGENT_SCORE_WEIGHTS: Final[dict[str, float]] = {
    "technical": 0.35,
    "market": 0.20,
    "sentiment": 0.10,
    "risk": 0.35,
}
MIN_AGENT_CONFIDENCE_TO_TRADE: Final[float] = 0.60
#: Hard ceiling on any agent's self-reported confidence. A model claiming 99%
#: certainty about a trade is a red flag, not an edge.
MAX_AGENT_CONFIDENCE: Final[float] = 0.95
#: Largest share of the decision that sentiment may influence.
MAX_SENTIMENT_INFLUENCE: Final[float] = 0.15

# ── Paper trading ───────────────────────────────────────────────────────────
DEFAULT_PAPER_BALANCE_USD: Final[float] = 10_000.0

# ── Agentic capital-control guardrail ──────────────────────────────────────
#: Loops (budget candles) the AI layer may analyse per symbol per cycle.
#: Prevents an autonomous agent from spinning on the same data.
MAX_ANALYSIS_LOOPS_PER_CYCLE: Final[int] = 1
#: Consecutive identical proposals the decision agent may emit before the
#: pipeline is considered stuck and halts for review.
MAX_CONSECUTIVE_IDENTICAL_PROPOSALS: Final[int] = 3
#: Portfolio-level cap on AI-proposed trades per rolling 24h.
MAX_AI_TRADES_PER_DAY: Final[int] = 10