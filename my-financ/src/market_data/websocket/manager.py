"""Real-time order-book streaming.

Websockets are optional infrastructure: the trading pipeline works on closed
candles and REST snapshots, so this module is a latency optimisation, not a
dependency. Every consumer must handle disconnection by falling back to REST.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from src.core.logging import get_logger
from src.schemas.market import Ticker

logger = get_logger(__name__)

BINANCE_WS_BASE = "wss://stream.binance.com:9443/stream"


@dataclass(slots=True)
class OrderBookLevel:
    price: float
    quantity: float


@dataclass(slots=True)
class OrderBook:
    symbol: str
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)
    last_update_id: int = 0

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> float | None:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None

    @property
    def spread_bps(self) -> float | None:
        if self.best_bid and self.best_ask and self.best_bid > 0:
            return (self.best_ask - self.best_bid) / self.mid * 10_000  # type: ignore[operator]
        return None

    @property
    def imbalance(self) -> float | None:
        """Bid volume share, 0..1. Above 0.5 means buy-side pressure."""
        bid_volume = sum(level.quantity for level in self.bids)
        ask_volume = sum(level.quantity for level in self.asks)
        total = bid_volume + ask_volume
        return bid_volume / total if total > 0 else None


def parse_binance_depth(payload: dict[str, Any]) -> OrderBook:
    """Parse a Binance depth-update payload into an :class:`OrderBook`."""
    data = payload.get("data", payload)
    return OrderBook(
        symbol=data.get("s", ""),
        bids=[OrderBookLevel(float(p), float(q)) for p, q in data.get("bids", data.get("b", []))],
        asks=[OrderBookLevel(float(p), float(q)) for p, q in data.get("asks", data.get("a", []))],
        last_update_id=int(data.get("lastUpdateId", data.get("u", 0)) or 0),
    )


def parse_binance_trade(payload: dict[str, Any]) -> tuple[str, float, float, bool]:
    """Return ``(symbol, price, quantity, is_buyer_maker)`` from a trade event."""
    data = payload.get("data", payload)
    return (
        data.get("s", ""),
        float(data.get("p", 0) or 0),
        float(data.get("q", 0) or 0),
        bool(data.get("m", False)),
    )


class BinanceWebSocketManager:
    """Reconnecting combined-stream client.

    Reconnect uses exponential backoff with a ceiling: a permanently dead
    socket must not turn into a tight reconnect loop that hammers the venue.
    """

    def __init__(
        self,
        symbols: list[str],
        streams: tuple[str, ...] = ("depth20@100ms", "trade"),
        base_url: str = BINANCE_WS_BASE,
        max_backoff: float = 60.0,
    ) -> None:
        self.symbols = symbols
        self.streams = streams
        self.base_url = base_url
        self.max_backoff = max_backoff
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.connected = False

    def _stream_url(self) -> str:
        from src.market_data.collectors.binance import to_binance_symbol

        topics = [
            f"{to_binance_symbol(symbol).lower()}@{stream}"
            for symbol in self.symbols
            for stream in self.streams
        ]
        return f"{self.base_url}?streams={'/'.join(topics)}"

    async def messages(self) -> AsyncIterator[dict[str, Any]]:
        """Yield decoded messages, reconnecting on failure."""
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "the 'websockets' package is required for live streaming; "
                "install it or rely on REST polling"
            ) from exc

        backoff = 1.0
        while not self._stop.is_set():
            try:
                async with websockets.connect(
                    self._stream_url(), ping_interval=20, ping_timeout=20, max_queue=512
                ) as socket:
                    self.connected = True
                    backoff = 1.0
                    logger.info("ws_connected", streams=len(self.symbols) * len(self.streams))
                    async for raw in socket:
                        if self._stop.is_set():
                            break
                        try:
                            yield json.loads(raw)
                        except json.JSONDecodeError:
                            logger.warning("ws_bad_payload", raw=raw[:200])
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - any failure must reconnect
                self.connected = False
                logger.warning("ws_disconnected", error=str(exc), retry_in=backoff)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except TimeoutError:
                    pass
                backoff = min(backoff * 2, self.max_backoff)

    def stop(self) -> None:
        self._stop.set()

    async def stream_tickers(self) -> AsyncIterator[Ticker]:
        """Convenience adapter yielding a ticker per trade event."""
        from src.schemas.base import utcnow

        async for message in self.messages():
            stream = message.get("stream", "")
            if "@trade" not in stream:
                continue
            symbol, price, quantity, _ = parse_binance_trade(message)
            if price <= 0:
                continue
            yield Ticker(symbol=symbol, last=price, volume_24h=quantity, timestamp=utcnow())