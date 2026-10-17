"""Feature engine: candles in, :class:`IndicatorSnapshot` out.

This is the single entry point to technical analysis. Strategies and agents both
consume its output, so indicator computation is defined in exactly one place
and cannot drift between them.
"""

from __future__ import annotations

import numpy as np

from src.core.constants import (
    ADX_PERIOD,
    ATR_PERIOD,
    BOLLINGER_PERIOD,
    BOLLINGER_STD,
    EMA_FAST,
    EMA_SLOW,
    MACD_FAST,
    MACD_SIGNAL,
    MACD_SLOW,
    PIVOT_LEFT,
    PIVOT_RIGHT,
    RSI_PERIOD,
    VOLUME_MA_PERIOD,
)
from src.core.exceptions import InsufficientDataError
from src.schemas.market import Candle, IndicatorSnapshot
from src.technical_analysis import support_resistance as sr_mod
from src.technical_analysis import trend as trend_mod
from src.technical_analysis import volume as volume_mod
from src.technical_analysis.indicators import adx as adx_mod
from src.technical_analysis.indicators import atr as atr_mod
from src.technical_analysis.indicators import bollinger as boll_mod
from src.technical_analysis.indicators import macd as macd_mod
from src.technical_analysis.indicators import rsi as rsi_mod
from src.technical_analysis.indicators.base import FloatArray, ema, sma


def _series(candles: list[Candle], attribute: str) -> FloatArray:
    return np.array([getattr(c, attribute) for c in candles], dtype=np.float64)


def _clean(value: float | None) -> float | None:
    """Convert nan to None so the snapshot is JSON-clean."""
    if value is None:
        return None
    as_float = float(value)
    return as_float if np.isfinite(as_float) else None


def compute_features(
    candles: list[Candle],
    *,
    timeframe: str | None = None,
    rsi_period: int = RSI_PERIOD,
    ema_fast: int = EMA_FAST,
    ema_slow: int = EMA_SLOW,
    bollinger_period: int = BOLLINGER_PERIOD,
    atr_period: int = ATR_PERIOD,
    adx_period: int = ADX_PERIOD,
    volume_ma: int = VOLUME_MA_PERIOD,
    minimum_bars: int = 60,
) -> IndicatorSnapshot:
    """Compute every indicator for the most recent completed bar.

    Raises :class:`InsufficientDataError` rather than returning partial
    indicators — a strategy must never act on a half-warmed-up toolkit.
    """
    if len(candles) < minimum_bars:
        raise InsufficientDataError(
            f"need at least {minimum_bars} candles to compute indicators, got {len(candles)}"
        )

    candles = sorted(candles, key=lambda c: c.timestamp)
    _opens = _series(candles, "open")  # no indicator consumes the open
    highs = _series(candles, "high")
    lows = _series(candles, "low")
    closes = _series(candles, "close")
    volumes = _series(candles, "volume")
    last = candles[-1]

    rsi_values = rsi_mod.rsi(closes, rsi_period)
    macd_line, macd_signal, macd_hist = macd_mod.compute(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    ema_fast_values = ema(closes, ema_fast)
    ema_slow_values = ema(closes, ema_slow)
    ema_200_values = ema(closes, 200) if closes.size > 200 else np.full(closes.size, np.nan)
    sma_20_values = sma(closes, 20)
    sma_50_values = sma(closes, 50)
    bands = boll_mod.bollinger(closes, bollinger_period, BOLLINGER_STD)
    atr_values = atr_mod.atr(highs, lows, closes, atr_period)
    atr_pct_values = atr_mod.atr_percent(atr_values, closes)
    adx_values, plus_di, minus_di = adx_mod.adx(highs, lows, closes, adx_period)
    vol_ratio_values = volume_mod.volume_ratio(volumes, volume_ma)
    levels = sr_mod.detect(highs, lows, closes, left=PIVOT_LEFT, right=PIVOT_RIGHT)

    trend_state = trend_mod.classify_trend(
        closes, ema_fast_values, ema_slow_values, _clean(float(adx_values[-1]))
    )
    regime = trend_mod.detect_regime(
        _clean(float(atr_pct_values[-1])),
        _clean(float(adx_values[-1])),
        trend_state,
    )

    return IndicatorSnapshot(
        symbol=last.symbol,
        timeframe=last.timeframe if timeframe is None else timeframe,  # type: ignore[arg-type]
        timestamp=last.timestamp,
        close=float(closes[-1]),
        rsi=_clean(float(rsi_values[-1])),
        macd=_clean(float(macd_line[-1])),
        macd_signal=_clean(float(macd_signal[-1])),
        macd_histogram=_clean(float(macd_hist[-1])),
        ema_fast=_clean(float(ema_fast_values[-1])),
        ema_slow=_clean(float(ema_slow_values[-1])),
        ema_200=_clean(float(ema_200_values[-1])),
        sma_20=_clean(float(sma_20_values[-1])),
        sma_50=_clean(float(sma_50_values[-1])),
        bollinger_upper=_clean(float(bands.upper[-1])),
        bollinger_middle=_clean(float(bands.middle[-1])),
        bollinger_lower=_clean(float(bands.lower[-1])),
        bollinger_width=_clean(float(bands.bandwidth[-1])),
        atr=_clean(float(atr_values[-1])),
        atr_pct=_clean(float(atr_pct_values[-1])),
        adx=_clean(float(adx_values[-1])),
        volume_ratio=_clean(float(vol_ratio_values[-1])),
        support=_clean(levels.support),
        resistance=_clean(levels.resistance),
        trend=trend_state.value,
        regime=regime,
    )


def compute_series_features(candles: list[Candle]) -> dict[str, FloatArray]:
    """Full indicator series, for the backtester and the chart endpoint.

    The backtester evaluates strategies bar-by-bar, so it needs the whole
    series rather than just the latest values.
    """
    if len(candles) < 60:
        raise InsufficientDataError(f"need at least 60 candles, got {len(candles)}")

    ordered = sorted(candles, key=lambda c: c.timestamp)
    highs = _series(ordered, "high")
    lows = _series(ordered, "low")
    closes = _series(ordered, "close")
    volumes = _series(ordered, "volume")

    macd_line, macd_signal, macd_hist = macd_mod.compute(closes)
    adx_values, plus_di, minus_di = adx_mod.adx(highs, lows, closes)
    bands = boll_mod.bollinger(closes)
    levels = sr_mod.detect(highs, lows, closes, left=PIVOT_LEFT, right=PIVOT_RIGHT)

    return {
        "open": _series(ordered, "open"),
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "rsi": rsi_mod.rsi(closes),
        "macd": macd_line,
        "macd_signal": macd_signal,
        "macd_hist": macd_hist,
        "ema_fast": ema(closes, EMA_FAST),
        "ema_slow": ema(closes, EMA_SLOW),
        "sma_20": sma(closes, 20),
        "sma_50": sma(closes, 50),
        "bollinger_upper": bands.upper,
        "bollinger_middle": bands.middle,
        "bollinger_lower": bands.lower,
        "bollinger_width": bands.bandwidth,
        "atr": atr_mod.atr(highs, lows, closes),
        "atr_pct": atr_mod.atr_percent(atr_mod.atr(highs, lows, closes), closes),
        "adx": adx_values,
        "plus_di": plus_di,
        "minus_di": minus_di,
        "volume_ratio": volume_mod.volume_ratio(volumes),
        "swing_highs": levels.pivot_highs,
        "swing_lows": levels.pivot_lows,
        "timestamp": np.array([c.timestamp for c in ordered]),
    }
