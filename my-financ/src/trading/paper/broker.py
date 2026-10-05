"""Paper broker: a simulated venue backed by real market data.

Paper trading is only meaningful if it is pessimistic. This adapter therefore:

* crosses the spread (buy at ask, sell at bid) rather than filling at mid,
* charges the same taker fee and slippage as the configured venue,
* rests limit orders that the market has not reached, and
* fills the remainder of a partially filled order on the next poll.

It writes every order, fill, trade, balance, and snapshot to the same tables the
live system uses, so a promotion decision is made on real recorded evidence
rather than on in-memory optimism.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.core.enums import TradingMode
from src.core.logging import get_logger
from src.core.security import idempotency_key
from src.database.base import new_id
from src.database.repositories import (
    OrderRepository,
    PortfolioRepository,
    TradeRepository,
)
from src.schemas.base import utcnow
from src.schemas.market import Ticker
from src.schemas.order import Order, OrderFill, OrderRequest
from src.schemas.portfolio import Position
from src.schemas.trade import Trade
from src.trading.base import (
    Broker,
    ExecutionInstruction,
    FillReport,
    fee_for,
    fill_price_for,
    side_value,
)

logger = get_logger(__name__)


class PaperBroker(Broker):
    """Simulated venue that persists to the database like a real one."""

    mode = TradingMode.PAPER

    def __init__(
        self,
        session: Session,
        *,
        taker_fee_rate: float,
        slippage_rate: float,
        quote_asset: str = "USDT",
        starting_cash: float = 10_000.0,
    ) -> None:
        self.session = session
        self.taker_fee_rate = taker_fee_rate
        self.slippage_rate = slippage_rate
        self.quote_asset = quote_asset
        self.starting_cash = starting_cash
        self.orders = OrderRepository(session)
        self.trades = TradeRepository(session)
        self.portfolio = PortfolioRepository(session)
        self._ensure_cash()

    # ── Balances ────────────────────────────────────────────────────────────
    def _ensure_cash(self) -> None:
        if self.portfolio.get_balance(self.quote_asset, self.mode.value) is None:
            self.portfolio.set_balance(self.quote_asset, self.mode.value, self.starting_cash)
            self.session.flush()

    def fetch_balances(self) -> dict[str, float]:
        balance = self.portfolio.get_balance(self.quote_asset, self.mode.value)
        return {self.quote_asset: balance.free if balance else self.starting_cash}

    # ── Order entry ─────────────────────────────────────────────────────────
    def submit(self, instruction: ExecutionInstruction, ticker: Ticker) -> FillReport:
        """Fill what the market allows now, rest the rest.

        Idempotent on the client order id: a repeated submission returns the
        original order instead of doubling the position.
        """
        request = instruction.request
        client_order_id = idempotency_key(
            "paper-order", request.symbol, side_value(request.side), request.idempotency_key or new_id()
        )

        existing = self.orders.by_client_order_id(client_order_id)
        if existing is not None:
            logger.info("paper_order_duplicate_ignored", symbol=request.symbol)
            return self._report(existing, request, ticker)

        quantity = self._clamp_to_cash(instruction, ticker)
        if quantity <= 0:
            raise ValueError(
                f"insufficient {self.quote_asset} to fill any of {instruction.quantity} {request.symbol}"
            )

        order = self.orders.create(
            Order(
                id=new_id(),
                client_order_id=client_order_id,
                symbol=request.symbol,
                side=request.side,
                order_type=request.order_type,
                status="open",
                quantity=quantity,
                stop_loss=instruction.stop_loss,
                take_profit=instruction.take_profit,
                mode=self.mode,
                strategy=request.strategy,
                signal_id=request.signal_id,
            ),
            signal_id=request.signal_id,
        )
        self.session.flush()

        report = self._try_fill(order, instruction, ticker)
        return report

    def _report(self, order: Order, request: OrderRequest, ticker: Ticker) -> FillReport:
        """Describe the stored order back to the caller."""
        return FillReport(
            order_id=order.id,
            client_order_id=order.client_order_id,
            symbol=order.symbol,
            side=str(getattr(order.side, "value", order.side)),
            status=order.status,
            requested_quantity=float(order.quantity),
            filled_quantity=float(order.filled_quantity),
            average_price=float(order.average_price) if order.average_price else None,
            fee_usd=float(order.fee_usd),
            slippage_bps=self.slippage_rate * 10_000,
            filled_at=order.updated_at,
            order=self.orders.to_schema(order),
        )

    def _clamp_to_cash(self, instruction: ExecutionInstruction, ticker: Ticker) -> float:
        """Never let a paper fill exceed settled cash or holdings.

        A live venue would reject the order for insufficient funds; simulating
        that rejection keeps paper results honest instead of silently inventing
        money or shorting an asset the account does not hold.
        """
        request = instruction.request
        if side_value(request.side) != "buy":
            base_asset = request.symbol.split("/")[0]
            holding = self.portfolio.get_balance(base_asset, self.mode.value)
            available = float(holding.free) if holding else 0.0
            if available + 1e-9 < instruction.quantity:
                raise ValueError(
                    f"insufficient {base_asset} to sell {instruction.quantity}; "
                    f"paper holds {available}"
                )
            return instruction.quantity

        reference = ticker.ask or ticker.last
        unit_cost = reference * (1 + self.slippage_rate)
        total_rate = self.taker_fee_rate + self.slippage_rate
        cash = self.fetch_balances()[self.quote_asset]
        affordable = cash / (unit_cost * (1 + self.taker_fee_rate)) if unit_cost > 0 else 0.0
        if total_rate and affordable <= 0:
            return 0.0
        return round(min(instruction.quantity, affordable), 10)

    def _try_fill(
        self,
        order: Order,
        instruction: ExecutionInstruction,
        ticker: Ticker,
    ) -> FillReport:
        price = fill_price_for(
            ticker,
            side_value(order.side),
            slippage_rate=self.slippage_rate,
            limit_price=instruction.request.limit_price,
            order_type=order.order_type,
        )

        if price is None:
            self.orders.update_status(order.id, "open")
            self.session.flush()
            return self._report(order, instruction.request, ticker)

        # Numeric columns come back as Decimal; the arithmetic below is float.
        order_qty = float(order.quantity)
        filled = float(order.filled_quantity)
        quantity = round(order_qty - filled, 10)
        notional = round(price * quantity, 10)
        fee = fee_for(notional, self.taker_fee_rate)

        self.orders.apply_fill(
            OrderFill(
                order_id=order.id,
                quantity=quantity,
                price=price,
                fee_usd=fee,
                slippage_bps=self.slippage_rate * 10_000,
                filled_at=utcnow(),
            )
        )
        self.session.flush()

        order = self.orders.get(order.id)
        assert order is not None
        fully_filled = float(order.filled_quantity) >= float(order.quantity)
        self.orders.update_status(order.id, "filled" if fully_filled else "partially_filled")
        self.session.flush()

        self._apply_to_book(order, price, fee, instruction)
        self.session.flush()

        report = self._report(self.orders.get(order.id) or order, instruction.request, ticker)
        logger.info(
            "paper_fill",
            symbol=order.symbol,
            side=side_value(order.side),
            qty=quantity,
            price=price,
            fee=fee,
            status=report.status,
        )
        return report

    def _apply_to_book(
        self,
        order: Order,
        price: float,
        fee: float,
        instruction: ExecutionInstruction,
    ) -> None:
        """Move cash and assets, then reconcile the position.

        Cash and asset legs live here and nowhere else. Splitting them between
        this method and :meth:`_close_position` previously debited the base
        asset twice on a reversal, which surfaced as "insufficient BTC" on a
        position the account demonstrably held.
        """
        base_asset = order.symbol.split("/")[0]
        is_buy = side_value(order.side) == "buy"
        quantity = float(order.quantity)
        if is_buy:
            cost = round(price * quantity + fee, 10)
            self.portfolio.debit(self.quote_asset, self.mode.value, cost)
            if base_asset:
                self.portfolio.credit(base_asset, self.mode.value, quantity)
        else:
            if base_asset:
                self.portfolio.debit(base_asset, self.mode.value, quantity)
            proceeds = round(price * quantity - fee, 10)
            self.portfolio.credit(self.quote_asset, self.mode.value, proceeds)

        # _sync_position owns closing the opposite-side position, and it knows
        # the true exit reason. Closing here too meant the first call won and
        # every exit was filed as "signal_flip".
        self._sync_position(order, price, fee, instruction, is_buy=is_buy)

    def _sync_position(
        self,
        order: Order,
        price: float,
        fee: float,
        instruction: ExecutionInstruction,
        *,
        is_buy: bool,
    ) -> None:
        """Reconcile the position table after cash has already been moved.

        Paper trading here is **spot only**: no leverage, no shorting. A sell
        therefore either trims an existing long or flattens it, and can never
        open a negative position. An earlier version reversed straight through
        into a short, which silently invented holdings the account never had.
        """
        existing = self.portfolio.get_position(order.symbol, self.mode.value)
        traded = float(order.quantity)

        if existing is None:
            if is_buy:
                self._open_position(order, price, fee, instruction)
            return

        held = float(existing.quantity)
        existing_is_long = side_value(existing.side) == "buy"

        if existing_is_long == is_buy:
            if is_buy:
                total = round(held + traded, 10)
                weighted = (float(existing.entry_price) * held + price * traded) / total
                self.portfolio.upsert_position(
                    existing.model_copy(
                        update={
                            "quantity": total,
                            "entry_price": round(weighted, 8),
                            "entry_fee_usd": round(existing.entry_fee_usd + fee, 8),
                            "current_price": price,
                            "stop_loss": instruction.stop_loss or existing.stop_loss,
                            "take_profit": instruction.take_profit or existing.take_profit,
                        }
                    )
                )
                self._record_trade(order, price, entry_price=weighted)
            else:
                # Trimming a long. The ledger slice is closed at close_position.
                remaining = round(held - traded, 10)
                self.portfolio.upsert_position(
                    existing.model_copy(
                        update={
                            "quantity": remaining,
                            "current_price": price,
                            "entry_fee_usd": round(
                                float(existing.entry_fee_usd) * (remaining / held), 8
                            ),
                        }
                    )
                )
                self._reopen_trade_remainder(existing, remaining)
            return

        # Sell against a long: realise it.
        self._close_position(existing, price, instruction.reason or "signal_flip")

    def _reopen_trade_remainder(self, position: Position, remaining: float) -> None:
        """Keep an open ledger row for the untrimmed part of a position."""
        if remaining <= 0:
            return
        from src.schemas.trade import Trade as TradeSchema

        row = TradeSchema(
            id=new_id(),
            order_id="",
            symbol=position.symbol,
            side=position.side,
            strategy=position.strategy,
            quantity=remaining,
            entry_price=float(position.entry_price),
            entry_time=position.opened_at,
            initial_risk_per_unit=(
                abs(float(position.entry_price) - float(position.stop_loss))
                if position.stop_loss
                else None
            ),
            mode=self.mode,
        )
        self.trades.open_trade(row)

    def _open_position(
        self,
        order: Order,
        price: float,
        fee: float,
        instruction: ExecutionInstruction,
    ) -> None:
        self.portfolio.upsert_position(
            Position(
                symbol=order.symbol,
                quantity=float(order.quantity),
                entry_price=price,
                side=side_value(order.side),
                current_price=price,
                stop_loss=instruction.stop_loss,
                take_profit=instruction.take_profit,
                strategy=order.strategy,
                mode=self.mode,
                entry_fee_usd=fee,
                opened_at=utcnow(),
            )
        )
        self._record_trade(order, price, entry_price=price)

    def _record_trade(self, order: Order, price: float, *, entry_price: float) -> None:
        """Open the ledger row for this round trip.

        Opened with zero fees: the trades table enforces ``pnl = gross - fees``,
        so an entry fee cannot be booked until the trip closes. Until then it
        lives on the position's ``entry_fee_usd``.
        """
        initial_risk = None
        if order.stop_loss:
            initial_risk = abs(float(entry_price) - float(order.stop_loss))

        self.trades.open_trade(
            Trade(
                id=new_id(),
                order_id=order.id,
                symbol=order.symbol,
                side=side_value(order.side),
                strategy=order.strategy,
                quantity=float(order.quantity),
                entry_price=round(entry_price, 8),
                entry_time=utcnow(),
                gross_pnl_usd=0.0,
                fees_usd=0.0,
                pnl_usd=0.0,
                initial_risk_per_unit=round(initial_risk, 8) if initial_risk else None,
                mode=self.mode,
            ),
            order_id=order.id,
        )

    def _close_position(self, position: Position, price: float, reason: str) -> None:
        """Realise a position. Cash has already been moved by the caller."""
        quantity = float(position.quantity)
        entry = float(position.entry_price)
        direction = 1.0 if side_value(position.side) == "buy" else -1.0
        gross = round(direction * (price - entry) * quantity, 8)
        exit_fee = fee_for(price * quantity, self.taker_fee_rate)
        total_fees = round(float(position.entry_fee_usd) + exit_fee, 8)
        net = round(gross - total_fees, 8)
        basis = round(entry * quantity, 8)
        pct = round(net / basis * 100, 8) if basis else 0.0
        risk_per_unit = (
            abs(entry - float(position.stop_loss)) if position.stop_loss else None
        )

        open_trade = next(
            (
                self.trades.to_schema(row)
                for row in self.trades.open_trades(self.mode.value)
                if row.symbol == position.symbol
            ),
            None,
        )
        if open_trade is not None:
            self.trades.close_trade(
                open_trade.model_copy(
                    update={
                        "exit_price": round(price, 8),
                        "exit_time": utcnow(),
                        "gross_pnl_usd": gross,
                        "fees_usd": total_fees,
                        "pnl_usd": net,
                        "pnl_pct": pct,
                        "risk_multiple": (
                            round(net / (risk_per_unit * quantity), 8) if risk_per_unit else None
                        ),
                        "exit_reason": reason,
                    }
                )
            )
        self.portfolio.close_position(position.symbol, self.mode.value)
        logger.info(
            "paper_position_closed",
            symbol=position.symbol,
            reason=reason,
            price=price,
            pnl=net,
        )

    # ── Management ───────────────────────────────────────────────────────────
    def cancel(self, client_order_id: str) -> bool:
        order = self.orders.by_client_order_id(client_order_id)
        if order is None or order.status not in ("pending", "open", "partially_filled"):
            return False
        self.orders.update_status(order.id, "cancelled")
        self.session.flush()
        return True

    def mark_to_market(self, tickers: dict[str, Ticker]) -> None:
        """Refresh open positions so unrealised P&L is not stale."""
        for position in self.portfolio.get_positions(self.mode.value):
            ticker = tickers.get(position.symbol)
            if ticker is None:
                continue
            self.portfolio.upsert_position(
                position.model_copy(update={"current_price": ticker.last})
            )
        self.session.flush()


__all__ = ["PaperBroker"]
