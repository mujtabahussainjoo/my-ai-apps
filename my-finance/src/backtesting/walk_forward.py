"""Chronological held-out evaluation; no tuning on the out-of-sample partition."""

import json
from dataclasses import replace
from hashlib import sha256

from src.backtesting.engine import BacktestEngine


def evaluate_split(candles, config, *, settings=None, fraction=0.7):
    if not 0.5 <= fraction <= 0.8:
        raise ValueError("training fraction must be between .5 and .8")
    series = sorted(candles, key=lambda candle: candle.timestamp)
    if len({c.timestamp for c in series}) != len(series):
        raise ValueError("duplicate candle timestamps")
    split = int(len(series) * fraction)
    if min(split, len(series) - split) < 300:
        raise ValueError("each evaluation partition requires at least 300 candles")
    engine = BacktestEngine(settings)
    in_config = replace(config, start=series[0].timestamp, end=series[split - 1].timestamp, label="in_sample")
    out_config = replace(
        config, start=series[split].timestamp, end=series[-1].timestamp, label="out_of_sample"
    )
    training = engine.run(series[:split], in_config)
    held_out = engine.run(series[split:], out_config, out_of_sample=True)
    inputs = [c.model_dump(mode="json") for c in series]
    identity = sha256(
        json.dumps([config.strategy, config.symbol, config.timeframe.value, inputs], sort_keys=True).encode()
    ).hexdigest()[:32]
    return training, held_out, identity
