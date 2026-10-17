"""Apply cumulative exchange fills once, preserving entry cost and net P&L."""

from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import select

from src.core.enums import OrderSide, TradingMode
from src.database.models.trading import Trade as TradeRow
from src.database.repositories import PortfolioRepository, TradeRepository
from src.schemas.portfolio import Position
from src.schemas.trade import Trade


def identity(*parts):
    return sha256(":".join(str(p) for p in parts).encode()).hexdigest()[:32]


class ExchangeLedger:
    def __init__(self, session):
        self.session = session
        self.trades = TradeRepository(session)
        self.portfolio = PortfolioRepository(session)

    def apply(self, order):
        quantity = float(order.filled_quantity)
        state = dict(order.raw_response or {})
        previous = float(state.get("reconciled_quantity", 0))
        delta = quantity - previous
        if delta <= 1e-12:
            return
        price = float(order.average_price or 0)
        if price <= 0:
            raise ValueError("Filled venue order has no average price")
        fee_total = float(order.fee_usd)
        fee = max(0, fee_total - float(state.get("reconciled_fee", 0)))
        # Derive the incremental fill price from the venue's cumulative average.
        prior_cost = float(state.get("reconciled_cost", 0))
        delta_price = (quantity * price - prior_cost) / delta
        mode = TradingMode(order.mode)
        now = datetime.now(UTC)
        if order.side == "buy":
            trade_id = identity("exchange-entry", order.id)
            row = self.trades.get(trade_id)
            trade = Trade(
                id=trade_id,
                order_id=order.id,
                symbol=order.symbol,
                side=OrderSide.BUY,
                strategy=order.strategy,
                quantity=quantity,
                entry_price=price,
                fees_usd=fee_total,
                gross_pnl_usd=0,
                pnl_usd=-fee_total,
                entry_time=row.entry_time if row else now,
                initial_risk_per_unit=abs(price - float(order.stop_loss)) if order.stop_loss else None,
                planned_risk_reward=abs(float(order.take_profit) - price)
                / abs(price - float(order.stop_loss))
                if order.take_profit and order.stop_loss and price != float(order.stop_loss)
                else None,
                mode=mode,
            )
            if row is None:
                self.trades.open_trade(trade)
            else:
                self.trades.close_trade(trade)
            self.portfolio.upsert_position(
                Position(
                    symbol=order.symbol,
                    quantity=quantity,
                    entry_price=price,
                    current_price=price,
                    stop_loss=float(order.stop_loss) if order.stop_loss else None,
                    take_profit=float(order.take_profit) if order.take_profit else None,
                    strategy=order.strategy,
                    mode=mode,
                    entry_fee_usd=fee_total,
                )
            )
        else:
            rows = list(
                self.session.scalars(
                    select(TradeRow)
                    .where(
                        TradeRow.symbol == order.symbol,
                        TradeRow.mode == order.mode,
                        TradeRow.is_open.is_(True),
                    )
                    .order_by(TradeRow.entry_time)
                )
            )
            remaining = delta
            for entry in rows:
                sold = min(remaining, float(entry.quantity))
                if sold <= 0:
                    break
                entry_fee = float(entry.fees_usd) * sold / float(entry.quantity)
                exit_fee = fee * sold / delta
                gross = (delta_price - float(entry.entry_price)) * sold
                net = gross - entry_fee - exit_fee
                risk = float(entry.initial_risk_per_unit or 0) * sold
                closed = Trade(
                    id=identity("exchange-exit", order.id, previous, entry.id),
                    order_id=order.id,
                    symbol=order.symbol,
                    side=OrderSide.BUY,
                    strategy=entry.strategy,
                    quantity=sold,
                    entry_price=float(entry.entry_price),
                    exit_price=delta_price,
                    entry_time=entry.entry_time,
                    exit_time=now,
                    gross_pnl_usd=gross,
                    fees_usd=entry_fee + exit_fee,
                    pnl_usd=net,
                    pnl_pct=net / (float(entry.entry_price) * sold) * 100,
                    initial_risk_per_unit=float(entry.initial_risk_per_unit)
                    if entry.initial_risk_per_unit
                    else None,
                    risk_multiple=net / risk if risk else None,
                    planned_risk_reward=float(entry.planned_risk_reward)
                    if entry.planned_risk_reward
                    else None,
                    exit_reason="manual",
                    mode=mode,
                )
                self.trades.close_trade(closed)
                if sold >= float(entry.quantity) - 1e-12:
                    self.session.delete(entry)
                else:
                    entry.quantity = float(entry.quantity) - sold
                    entry.fees_usd = float(entry.fees_usd) - entry_fee
                    entry.pnl_usd = -float(entry.fees_usd)
                remaining -= sold
            if remaining > 1e-10:
                # External inventory has no trustworthy cost basis; do not invent P&L.
                from src.database.repositories import SystemEventRepository

                SystemEventRepository(self.session).log(
                    "exchange",
                    "external_inventory_exit",
                    "Exit contains inventory without recorded entry basis; P&L requires operator reconciliation",
                    level="warning",
                    context={"order_id": order.id, "quantity": remaining},
                )
        order.raw_response = {
            **state,
            "reconciled_quantity": quantity,
            "reconciled_fee": fee_total,
            "reconciled_cost": quantity * price,
        }
        self.session.flush()


def reconcile_orders(session, broker):
    from src.database.repositories import OrderRepository
    from src.portfolio.manager import PortfolioManager

    repository = OrderRepository(session)
    ledger = ExchangeLedger(session)
    count = 0
    for order in repository.recent(limit=1000, mode=broker.mode.value):
        if order.status in ("cancelled", "rejected", "filled") and (order.raw_response or {}).get(
            "reconciled_quantity"
        ) == float(order.filled_quantity):
            continue
        raw = broker._client.fetch_order(order.id, order.symbol)
        from src.schemas.order import OrderRequest

        request = OrderRequest(
            symbol=order.symbol,
            side=order.side,
            order_type=order.order_type,
            quantity=float(order.quantity),
            limit_price=float(order.limit_price) if order.limit_price else None,
            mode=broker.mode,
        )
        report = broker._to_report(raw, request)
        order.status = report.status
        order.filled_quantity = report.filled_quantity
        order.average_price = report.average_price
        order.fee_usd = report.fee_usd
        ledger.apply(order)
        count += 1
    session.commit()
    PortfolioManager(session, broker).sync()
    return count
