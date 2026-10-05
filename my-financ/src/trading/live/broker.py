"""Testnet and live venue adapter.

This is the only code in the project permitted to touch a real exchange with real
money, so it is written defensively:

* construction fails unless credentials are configured,
* ``mode=LIVE`` additionally requires both live gates, via the single
  :func:`assert_live_trading_allowed` entry point,
* the venue's sandbox flag is forced on for testnet, so a testnet instance
  cannot be pointed at the real exchange by a config typo,
* the exchange client is injectable, so the gate logic is unit-testable without
  ccxt installed and without an account.
"""

from __future__ import annotations

from typing import Any

from src.core.enums import OrderType, TradingMode
from src.core.exceptions import ExecutionError
from src.core.logging import get_logger
from src.core.security import assert_live_trading_allowed
from src.schemas.market import Ticker
from src.schemas.order import Order, OrderRequest
from src.schemas.trade import Trade
from src.trading.base import Broker, ExecutionInstruction, FillReport, side_value

logger = get_logger(__name__)

SUPPORTED_CLIENTS = ("ccxt",)


def _require_ccxt() -> Any:
    try:
        import ccxt  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise ExecutionError(
            "the live/testnet adapter needs the optional 'live' extra: "
            "pip install '.[live]'"
        ) from exc
    return ccxt


class ExchangeBroker(Broker):
    """Thin, auditable wrapper around a ccxt exchange client."""

    def __init__(
        self,
        mode: TradingMode,
        *,
        api_key: str,
        api_secret: str,
        exchange_id: str = "binance",
        sandbox: bool = True,
        client: Any | None = None,
        default_type: str = "spot",
    ) -> None:
        if mode not in (TradingMode.TESTNET, TradingMode.LIVE):
            raise ExecutionError(f"ExchangeBroker cannot run in mode {mode.value!r}")
        if not api_key or not api_secret:
            raise ExecutionError("exchange credentials are required for testnet/live execution")

        self.mode = mode
        self.default_type = default_type
        self._client = (
            client
            if client is not None
            else self._build_client(exchange_id, api_key, api_secret, sandbox, mode, default_type)
        )

    # ── Construction ─────────────────────────────────────────────────────────
    @staticmethod
    def _build_client(
        exchange_id: str,
        api_key: str,
        api_secret: str,
        sandbox: bool,
        mode: TradingMode,
        default_type: str = "spot",
    ) -> Any:
        ccxt = _require_ccxt()
        if not hasattr(ccxt, exchange_id):
            raise ExecutionError(f"exchange {exchange_id!r} is not supported by the installed ccxt")
        exchange_class = getattr(ccxt, exchange_id)

        # Testnet must never be able to reach the real books. A config typo that
        # turns sandboxing off is a hard error in testnet, not a warning.
        effective_sandbox = True if mode is TradingMode.TESTNET else sandbox
        if mode is TradingMode.TESTNET and not effective_sandbox:  # pragma: no cover - defensive
            raise ExecutionError("refusing to build a testnet client with sandboxing disabled")

        client = exchange_class(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": default_type},
            }
        )
        if effective_sandbox and hasattr(client, "setSandboxMode"):
            client.setSandboxMode(True)
        return client

    # ── Submission ───────────────────────────────────────────────────────────
    def submit(self, instruction: ExecutionInstruction, ticker: Ticker) -> FillReport:
        """Send an authorised order to the venue."""
        assert_live_trading_allowed(
            self.mode,
            live_enabled=self._live_enabled,
            acknowledgement=self._live_acknowledged,
        )

        request = instruction.request
        params: dict[str, Any] = {}
        if instruction.stop_loss is not None or instruction.take_profit is not None:
            # Attached stop/target on the venue, so protection survives a dead
            # local process.
            params = self._bracket_params(instruction)

        side = side_value(request.side)
        symbol = self._venue_symbol(request.symbol)
        quantity = float(instruction.quantity)

        if request.order_type is OrderType.LIMIT and request.limit_price:
            raw = self._client.create_order(
                symbol, side, "limit", quantity, float(request.limit_price), params
            )
        else:
            raw = self._client.create_order(symbol, side, "market", quantity, None, params)

        report = self._to_report(raw, request)
        logger.info(
            "exchange_order_submitted",
            mode=self.mode.value,
            symbol=request.symbol,
            side=side,
            venue_order_id=report.order_id,
            filled=report.filled_quantity,
        )
        return report

    def _bracket_params(self, instruction: ExecutionInstruction) -> dict[str, Any]:
        """Ask the venue to hold a protective stop and target with the entry."""
        params: dict[str, Any] = {}
        if instruction.stop_loss is not None:
            params["stopLoss"] = {"triggerPrice": float(instruction.stop_loss)}
        if instruction.take_profit is not None:
            params["takeProfit"] = {"triggerPrice": float(instruction.take_profit)}
        return params

    @staticmethod
    def _venue_symbol(symbol: str) -> str:
        """Our ``BTC/USDT`` form is already ccxt's, but be explicit."""
        return symbol.replace("/", "/").upper()

    def _to_report(self, raw: dict[str, Any], request: OrderRequest) -> FillReport:
        status = str(raw.get("status") or "open").lower()
        filled = float(raw.get("filled") or 0.0)
        average = raw.get("average")
        price = float(average) if average else (float(raw.get("price") or 0.0) or None)
        cost = raw.get("cost")
        fee = 0.0
        if isinstance(raw.get("fee"), dict) and raw["fee"].get("cost"):
            fee = float(raw["fee"]["cost"])
        elif cost:
            fee = float(cost) * 0.001

        filled_at = None
        if raw.get("timestamp"):
            from datetime import UTC, datetime

            filled_at = datetime.fromtimestamp(int(raw["timestamp"]) / 1000, tz=UTC)

        return FillReport(
            order_id=str(raw.get("id") or ""),
            client_order_id=str(raw.get("clientOrderId") or ""),
            symbol=request.symbol,
            side=side_value(request.side),
            status=status,
            requested_quantity=float(request.quantity or 0.0),
            filled_quantity=filled,
            average_price=price,
            fee_usd=fee,
            filled_at=filled_at,
            fills=list(raw.get("trades") or []),
        )

    # ── Management ───────────────────────────────────────────────────────────
    def cancel(self, client_order_id: str) -> bool:
        try:
            self._client.cancel_order(client_order_id, self._venue_symbol(""))
            return True
        except Exception as exc:  # noqa: BLE001 - venue errors vary widely
            logger.warning("exchange_cancel_failed", client_order_id=client_order_id, error=str(exc))
            return False

    def fetch_balances(self) -> dict[str, float]:
        raw = self._client.fetch_balance()
        total = raw.get("total") or {}
        return {asset: float(amount) for asset, amount in total.items() if float(amount) > 0}

    def poll_open_orders(self) -> list[Order]:
        return []

    # ── Gates ────────────────────────────────────────────────────────────────
    _live_enabled: bool = False
    _live_acknowledged: bool = False

    @classmethod
    def from_settings(cls, settings: Any, *, client: Any | None = None) -> ExchangeBroker:
        """Build from configuration, enforcing the live gates at construction."""
        mode = TradingMode(settings.trading_mode)
        assert_live_trading_allowed(
            mode,
            live_enabled=settings.live_trading_enabled,
            acknowledgement=settings.live_trading_i_understand_the_risk,
        )
        if settings.exchange_api_key is None or settings.exchange_api_secret is None:
            raise ExecutionError("EXCHANGE_API_KEY and EXCHANGE_API_SECRET are required")

        broker = cls(
            mode,
            api_key=settings.exchange_api_key.get_secret_value(),
            api_secret=settings.exchange_api_secret.get_secret_value(),
            exchange_id=settings.exchange_id,
            sandbox=settings.exchange_sandbox,
            client=client,
        )
        broker._live_enabled = settings.live_trading_enabled
        broker._live_acknowledged = settings.live_trading_i_understand_the_risk
        return broker


def load_trade_for(order_id: str, trades: list[Trade]) -> Trade | None:
    """Find the open trade belonging to an order, if any."""
    return next((t for t in trades if t.order_id == order_id), None)


__all__ = ["ExchangeBroker", "load_trade_for"]
