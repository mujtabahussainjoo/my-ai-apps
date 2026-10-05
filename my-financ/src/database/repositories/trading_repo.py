"""Order, fill and trade persistence.

The idempotency guarantee lives here. ``client_order_id`` carries the key from
:mod:`src.core.security`, and the column is unique, so a retried request
returns the original order instead of placing a second one. That is enforced by
the database, not by a check-then-insert in Python, which would still race.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.database.base import utcnow
from src.database.models import Approval, Order, OrderFill, Trade
from src.database.repositories import mappers
from src.schemas.order import Approval as ApprovalSchema
from src.schemas.order import Order as OrderSchema
from src.schemas.order import OrderFill as FillSchema
from src.schemas.trade import Trade as TradeSchema

logger = get_logger(__name__)


class OrderRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, order: OrderSchema, signal_id: str | None = None) -> Order:
        row = Order(**mappers.order_to_row(order))
        row.signal_id = signal_id
        self.session.add(row)
        try:
            self.session.flush()
        except IntegrityError as exc:
            # The unique constraint is the replay guard, so this is an expected
            # outcome, not an error to propagate.
            self.session.rollback()
            logger.info("order_replay_detected", client_order_id=order.client_order_id)
            existing = self.by_client_order_id(order.client_order_id)
            if existing is not None:
                return existing
            raise exc
        return row

    def by_client_order_id(self, client_order_id: str) -> Order | None:
        return self.session.scalar(
            select(Order).where(Order.client_order_id == client_order_id)
        )

    def get(self, order_id: str) -> Order | None:
        return self.session.get(Order, order_id)

    def update_status(
        self, order_id: str, status: str, *, reason: str | None = None
    ) -> Order | None:
        row = self.get(order_id)
        if row is None:
            return None
        row.status = status
        if reason:
            row.reject_reason = reason
        self.session.flush()
        return row

    def apply_fill(self, fill: FillSchema) -> None:
        """Record a fill and keep the order's aggregate quantity in step.

        Rejects an over-fill in the database rather than trusting the caller:
        an order filled beyond its size is a bug that would otherwise become a
        position larger than the one the risk engine approved.
        """
        row = self.get(fill.order_id)
        if row is None:
            raise ValueError(f"fill references unknown order {fill.order_id}")

        # Accumulating fills in binary floating point drifts: 0.1 + 0.2 is
        # 0.30000000000000004, which would trip the over-fill guard below and
        # reject a perfectly valid order. Quantise to the column's scale and
        # allow a tolerance far below any real over-fill.
        new_filled = round(float(row.filled_quantity) + fill.quantity, 10)
        tolerance = max(float(row.quantity) * 1e-9, 1e-9)
        if new_filled > float(row.quantity) + tolerance:
            raise ValueError(
                f"over-fill: order {fill.order_id} has {row.filled_quantity} of "
                f"{row.quantity} filled, cannot add {fill.quantity}"
            )
        self.session.add(
            OrderFill(
                order_id=fill.order_id,
                quantity=mappers.d(fill.quantity),
                price=mappers.d(fill.price),
                fee_usd=mappers.d(fill.fee_usd),
                slippage_bps=mappers.d(fill.slippage_bps),
                filled_at=mappers.dt(fill.filled_at),
            )
        )
        row.filled_quantity = mappers.d(new_filled)
        row.fee_usd = mappers.d(float(row.fee_usd) + fill.fee_usd)
        if fill.quantity > 0:
            # Volume-weighted average price across all fills.
            prior_qty = float(row.filled_quantity) - fill.quantity
            prior_avg = float(row.average_price or 0.0)
            row.average_price = mappers.d(
                (prior_avg * prior_qty + fill.price * fill.quantity)
                / (prior_qty + fill.quantity)
            )
        self.session.flush()

    def recent(self, limit: int = 50, mode: str | None = None) -> list[Order]:
        stmt = select(Order).order_by(Order.created_at.desc()).limit(limit)
        if mode:
            stmt = stmt.where(Order.mode == mode)
        return list(self.session.scalars(stmt))

    def open_orders(self, mode: str | None = None) -> list[Order]:
        stmt = select(Order).where(
            Order.status.in_(["pending", "partially_filled", "submitted"])
        )
        if mode:
            stmt = stmt.where(Order.mode == mode)
        return list(self.session.scalars(stmt))

    def count(self, mode: str | None = None, since: datetime | None = None) -> int:
        stmt = select(func.count()).select_from(Order)
        if mode:
            stmt = stmt.where(Order.mode == mode)
        if since:
            stmt = stmt.where(Order.created_at >= since)
        return int(self.session.scalar(stmt) or 0)

    def to_schema(self, row: Order) -> OrderSchema:
        return mappers.row_to_order(row)


class TradeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def open_trade(self, trade: TradeSchema, order_id: str | None = None) -> Trade:
        row = Trade(**mappers.trade_to_row(trade))
        row.order_id = order_id or trade.order_id or None
        self.session.add(row)
        self.session.flush()
        return row

    def close_trade(self, trade: TradeSchema, order_id: str | None = None) -> Trade:
        """Upsert on close so the entry row is replaced, not duplicated."""
        row = self.session.get(Trade, trade.id)
        payload = mappers.trade_to_row(trade)
        if row is None:
            row = Trade(**payload)
            row.order_id = order_id or trade.order_id or None
            self.session.add(row)
        else:
            for key, value in payload.items():
                setattr(row, key, value)
        self.session.flush()
        return row

    def get(self, trade_id: str) -> Trade | None:
        return self.session.get(Trade, trade_id)

    def open_trades(self, mode: str | None = None) -> list[Trade]:
        stmt = select(Trade).where(Trade.is_open.is_(True))
        if mode:
            stmt = stmt.where(Trade.mode == mode)
        return list(self.session.scalars(stmt))

    def closed_trades(
        self,
        mode: str | None = None,
        strategy: str | None = None,
        since: datetime | None = None,
        limit: int | None = None,
    ) -> list[Trade]:
        stmt = select(Trade).where(Trade.is_open.is_(False))
        if mode:
            stmt = stmt.where(Trade.mode == mode)
        if strategy:
            stmt = stmt.where(Trade.strategy == strategy)
        if since:
            stmt = stmt.where(Trade.exit_time >= since)
        stmt = stmt.order_by(Trade.exit_time.asc())
        if limit:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def realized_pnl(self, mode: str | None = None, since: datetime | None = None) -> float:
        """Net realised P&L in USD, computed by the database in exact numeric.

        The engine keeps ``pnl_usd`` consistent with ``gross - fees`` via a
        check constraint; summing it here rather than re-deriving in Python
        means the audit trail and the dashboard cannot disagree.
        """
        stmt = select(func.coalesce(func.sum(Trade.pnl_usd), 0)).where(
            Trade.is_open.is_(False)
        )
        if mode:
            stmt = stmt.where(Trade.mode == mode)
        if since:
            stmt = stmt.where(Trade.exit_time >= since)
        return mappers.f(self.session.scalar(stmt))

    def to_schema(self, row: Trade) -> TradeSchema:
        return mappers.row_to_trade(row)


class ApprovalRepository:
    """Human sign-off records for live orders."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def request(self, fingerprint: str, order_id: str | None = None) -> ApprovalSchema:
        row = Approval(fingerprint=fingerprint, order_id=order_id)
        self.session.add(row)
        self.session.flush()
        return ApprovalSchema(
            id=row.id,
            fingerprint=row.fingerprint,
            status=row.status,
            order_id=row.order_id,
            created_at=row.created_at,
        )

    def decide(
        self, approval_id: str, approved: bool, operator: str, note: str | None = None
    ) -> Approval | None:
        row = self.session.get(Approval, approval_id)
        if row is None:
            return None
        row.status = "approved" if approved else "rejected"
        row.approved_by = operator
        row.approved_at = utcnow()
        row.note = note
        # A short expiry: an approval for yesterday's price is not an approval
        # for today's.
        row.expires_at = utcnow() + timedelta(minutes=5)
        self.session.flush()
        return row

    def valid_for(self, fingerprint: str) -> Approval | None:
        """An unexpired approval matching this exact order."""
        now = utcnow()
        return self.session.scalar(
            select(Approval).where(
                Approval.fingerprint == fingerprint,
                Approval.status == "approved",
                Approval.expires_at.is_not(None),
                Approval.expires_at > now,
            )
        )

    def pending(self) -> list[Approval]:
        return list(
            self.session.scalars(
                select(Approval).where(Approval.status == "pending").order_by(Approval.created_at)
            )
        )