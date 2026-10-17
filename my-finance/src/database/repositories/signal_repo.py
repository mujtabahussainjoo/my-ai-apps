"""Signal persistence.

Signals are written before they are acted on, so any order in the ledger can be
traced to the deterministic reasoning that produced it. Without that link, a
losing trade is unexplainable after the fact.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.database.base import new_id
from src.database.models.trading import Signal as SignalRow
from src.schemas.base import utcnow
from src.schemas.signal import Signal, SignalAction, Timeframe


class SignalRepository:
    """Reads and writes strategy signals."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def record(self, signal: Signal) -> str:
        """Store a signal and return its generated id for order linkage."""
        signal_id = new_id()
        self.session.add(
            SignalRow(
                id=signal_id,
                symbol=signal.symbol,
                timeframe=signal.timeframe.value,
                strategy=signal.strategy,
                strategy_version=signal.strategy_version,
                action=str(signal.action.value).lower(),
                confidence=float(signal.confidence),
                entry=float(signal.entry),
                stop_loss=float(signal.stop_loss) if signal.stop_loss else None,
                take_profit=float(signal.take_profit) if signal.take_profit else None,
                atr=float(signal.atr) if signal.atr else None,
                # mode="json" matters: SignalScore.computed_at is a datetime and
                # a plain model_dump() leaves it as a datetime object, which the
                # JSON serializer rejects at flush time.
                score=signal.score.model_dump(mode="json") if signal.score else None,
                rationale=[r.model_dump(mode="json") for r in signal.rationale] or None,
                created_at=signal.created_at,
            )
        )
        self.session.flush()
        return signal_id

    # -- lifecycle ---------------------------------------------------------
    # A signal's outcome is recorded whether or not it produced an order. The
    # rejection case is the one that matters most and used to be invisible.

    def pending(self, limit: int = 20) -> list[SignalRow]:
        """Undecided signals, oldest first, so the queue is drained in order."""
        stmt = (
            select(SignalRow).where(SignalRow.status == "pending").order_by(SignalRow.created_at).limit(limit)
        )
        return list(self.session.scalars(stmt))

    def claim(self, signal_id: str) -> bool:
        result = self.session.execute(
            update(SignalRow)
            .where(SignalRow.id == signal_id, SignalRow.status == "pending")
            .values(status="processing")
        )
        self.session.commit()
        return result.rowcount == 1

    def defer(self, signal_id: str) -> None:
        self.session.execute(
            update(SignalRow)
            .where(SignalRow.id == signal_id, SignalRow.status == "processing")
            .values(status="pending")
        )
        self.session.commit()

    def mark_executed(self, signal_id: str, order_id: str) -> None:
        """Record that a signal became an order."""
        self._settle(signal_id, status="executed", order_id=order_id)

    def mark_rejected(self, signal_id: str, reason: str) -> None:
        """Record that a signal was considered and declined.

        No order exists to link, so the reason is the whole audit trail.
        """
        self._settle(signal_id, status="rejected", reject_reason=reason)

    def mark_ignored(self, signal_id: str, reason: str) -> None:
        """Record that a signal needed no action (``hold``, stale, duplicate)."""
        self._settle(signal_id, status="ignored", reject_reason=reason)

    def _settle(
        self,
        signal_id: str,
        *,
        status: str,
        order_id: str | None = None,
        reject_reason: str | None = None,
    ) -> None:
        row = self.session.get(SignalRow, signal_id)
        if row is None:
            raise LookupError(f"signal {signal_id} does not exist")
        row.status = status
        row.processed_at = utcnow()
        if order_id is not None:
            row.order_id = order_id
        if reject_reason is not None:
            row.reject_reason = reject_reason
        self.session.flush()

    def get(self, signal_id: str) -> Signal | None:
        row = self.session.get(SignalRow, signal_id)
        return self.to_schema(row) if row else None

    def recent(
        self,
        symbol: str | None = None,
        strategy: str | None = None,
        limit: int = 50,
    ) -> list[Signal]:
        stmt = select(SignalRow).order_by(SignalRow.created_at.desc()).limit(limit)
        if symbol:
            stmt = stmt.where(SignalRow.symbol == symbol)
        if strategy:
            stmt = stmt.where(SignalRow.strategy == strategy)
        return [self.to_schema(row) for row in self.session.scalars(stmt)]

    def count(self, since: datetime | None = None) -> int:
        stmt = select(SignalRow)
        if since:
            stmt = stmt.where(SignalRow.created_at >= since)
        return len(list(self.session.scalars(stmt)))

    def lifecycle(self, signal_id: str) -> dict[str, str | None]:
        """The outcome fields, for callers that read a row rather than a schema."""
        row = self.session.get(SignalRow, signal_id)
        if row is None:
            return {}
        return {
            "status": row.status,
            "order_id": row.order_id,
            "reject_reason": row.reject_reason,
        }

    def to_schema(self, row: SignalRow) -> Signal:
        from src.schemas.signal import Rationale, SignalScore

        return Signal(
            id=row.id,
            symbol=row.symbol,
            timeframe=Timeframe(row.timeframe),
            strategy=row.strategy,
            strategy_version=row.strategy_version,
            action=SignalAction(row.action.upper()),
            confidence=float(row.confidence),
            entry=float(row.entry),
            stop_loss=float(row.stop_loss) if row.stop_loss is not None else None,
            take_profit=float(row.take_profit) if row.take_profit is not None else None,
            atr=float(row.atr) if row.atr is not None else None,
            score=SignalScore(**row.score) if row.score else None,
            rationale=[Rationale(**r) for r in (row.rationale or [])],
            created_at=row.created_at or utcnow(),
        )


__all__ = ["SignalRepository"]
