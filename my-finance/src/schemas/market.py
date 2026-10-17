"""Market data schemas: candles, tickers, snapshots, metadata."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import Field, field_validator

from src.core.enums import MarketRegime, Timeframe
from src.schemas.base import (
    Base,
    NonNegativeFloat,
    Price,
    utcnow,
)


class Candle(Base):
    """One OHLCV bar. ``timestamp`` is the bar open time in UTC."""

    timestamp: datetime
    open: Price
    high: Price
    low: Price
    close: Price
    volume: NonNegativeFloat
    symbol: str = "BTC/USDT"
    timeframe: Timeframe = Timeframe.H1

    @field_validator("timestamp")
    @classmethod
    def _require_tz(cls, value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    @property
    def typical_price(self) -> float:
        return (self.high + self.low + self.close) / 3

    @property
    def bar_range(self) -> float:
        return self.high - self.low

    @property
    def body_pct(self) -> float:
        if self.open <= 0:
            return 0.0
        return abs(self.close - self.open) / self.open * 100

    @property
    def is_bullish(self) -> bool:
        return self.close >= self.open

    @property
    def age_seconds(self) -> float:
        return max(0.0, (utcnow() - self.timestamp).total_seconds())


class Ticker(Base):
    symbol: str
    last: Price
    bid: Price | None = None
    ask: Price | None = None
    volume_24h: NonNegativeFloat | None = None
    timestamp: datetime = Field(default_factory=utcnow)

    @property
    def mid(self) -> float:
        if self.bid and self.ask:
            return (self.bid + self.ask) / 2
        return self.last

    @property
    def spread_bps(self) -> float | None:
        if not self.bid or not self.ask or self.bid <= 0:
            return None
        return (self.ask - self.bid) / ((self.ask + self.bid) / 2) * 10_000

    @property
    def age_seconds(self) -> float:
        return max(0.0, (utcnow() - self.timestamp).total_seconds())


class MarketSnapshot(Base):
    """Everything the market/TA agents need about one symbol at one instant."""

    symbol: str
    ticker: Ticker
    candles: list[Candle] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=utcnow)

    @property
    def last_price(self) -> float:
        return self.ticker.last

    @property
    def candle_count(self) -> int:
        return len(self.candles)

    @property
    def is_stale(self) -> bool:
        from src.core.constants import MAX_QUOTE_AGE_SECONDS

        return self.ticker.age_seconds > MAX_QUOTE_AGE_SECONDS


class CoinMetadata(Base):
    """CoinGecko-style metadata. Supplementary context, never price truth."""

    symbol: str
    name: str
    market_cap: NonNegativeFloat | None = None
    market_cap_rank: int | None = None
    total_volume: NonNegativeFloat | None = None
    price_change_percentage_24h: float | None = None
    circulating_supply: NonNegativeFloat | None = None
    ath: float | None = None
    ath_change_percentage: float | None = None
    last_updated: datetime = Field(default_factory=utcnow)


class IndicatorSnapshot(Base):
    """Computed indicator values for the latest completed bar."""

    symbol: str
    timeframe: Timeframe
    timestamp: datetime
    close: Price
    rsi: float | None = Field(default=None, ge=0, le=100)
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None
    ema_fast: float | None = None
    ema_slow: float | None = None
    ema_200: float | None = None
    sma_20: float | None = None
    sma_50: float | None = None
    bollinger_upper: float | None = None
    bollinger_middle: float | None = None
    bollinger_lower: float | None = None
    bollinger_width: float | None = None
    atr: float | None = None
    atr_pct: float | None = None
    adx: float | None = None
    volume_ratio: float | None = None
    support: float | None = None
    resistance: float | None = None
    trend: str | None = None
    regime: MarketRegime = MarketRegime.RANGE

    @property
    def macd_state(self) -> str:
        if self.macd is None or self.macd_signal is None:
            return "unknown"
        return "bullish" if self.macd > self.macd_signal else "bearish"

    @property
    def ema_state(self) -> str:
        if self.ema_fast is None or self.ema_slow is None:
            return "unknown"
        return "bullish" if self.ema_fast > self.ema_slow else "bearish"

    @property
    def rsi_state(self) -> str:
        if self.rsi is None:
            return "unknown"
        if self.rsi <= 30:
            return "oversold"
        if self.rsi >= 70:
            return "overbought"
        return "neutral"

    def to_features(self) -> dict[str, float | str | None]:
        """Flat numeric view for prompts and scoring. No nested structures."""
        return {
            "rsi": self.rsi,
            "macd_state": self.macd_state,
            "macd_histogram": self.macd_histogram,
            "ema_state": self.ema_state,
            "ema_fast": self.ema_fast,
            "ema_slow": self.ema_slow,
            "atr_pct": self.atr_pct,
            "adx": self.adx,
            "volume_ratio": self.volume_ratio,
            "bollinger_width": self.bollinger_width,
            "support": self.support,
            "resistance": self.resistance,
            "trend": self.trend,
            "regime": self.regime.value,
        }


class MarketContext(Base):
    """Cross-market context for regime detection and correlation checks."""

    btc_dominance: float | None = Field(default=None, ge=0, le=100)
    fear_greed_index: int | None = Field(default=None, ge=0, le=100)
    total_market_cap_usd: NonNegativeFloat | None = None
    btc_24h_change_pct: float | None = None
    symbol_correlations: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    as_of: datetime = Field(default_factory=utcnow)
