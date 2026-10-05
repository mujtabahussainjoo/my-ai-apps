"""Candle persistence.

Bulk insert is the interesting path: a year of 1h candles is ~8,760 rows and
inserting them one at a time is minutes of round trips. ``upsert_many`` uses a
single statement and relies on the unique constraint to decide insert vs update,
which also makes re-downloading overlapping history harmless.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from sqlalchemy.sql import Insert

from src.core.enums import Timeframe
from src.core.logging import get_logger
from src.database.models import Candle
from src.database.repositories import mappers
from src.schemas.market import Candle as CandleSchema

logger = get_logger(__name__)

#: Above this, chunk the statement so a huge history cannot exceed the
#: 65535 bind-parameter limit in Postgres.
CHUNK = 2000


class CandleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, candles: Iterable[CandleSchema]) -> int:
        rows = [mappers.candle_to_row(c) for c in candles]
        if not rows:
            return 0

        written = 0
        for start in range(0, len(rows), CHUNK):
            chunk = rows[start : start + CHUNK]
            self._upsert_chunk(chunk)
            written += len(chunk)
        self.session.flush()
        logger.info("candles_upserted", count=written)
        return written

    def _upsert_chunk(self, rows: Sequence[dict]) -> None:
        stmt: Insert
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            stmt = pg_insert(Candle)
        else:
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            stmt = sqlite_insert(Candle)

        update_cols = {
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
        }
        self.session.execute(
            stmt.on_conflict_do_update(
                index_elements=[Candle.symbol, Candle.timeframe, Candle.timestamp],
                set_=update_cols,
            ).values(rows)
        )

    def get_range(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int | None = None,
        ascending: bool = True,
    ) -> list[CandleSchema]:
        """Oldest-first, which is the only order indicators may be computed in."""
        stmt = select(Candle).where(
            Candle.symbol == symbol, Candle.timeframe == timeframe.value
        )
        if start is not None:
            stmt = stmt.where(Candle.timestamp >= start)
        if end is not None:
            stmt = stmt.where(Candle.timestamp <= end)
        stmt = stmt.order_by(
            Candle.timestamp.asc() if ascending else Candle.timestamp.desc()
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        return [mappers.row_to_candle(row) for row in self.session.scalars(stmt)]

    def latest(self, symbol: str, timeframe: Timeframe, count: int = 1) -> list[CandleSchema]:
        return self.get_range(symbol, timeframe, limit=count, ascending=False)

    def count(self, symbol: str, timeframe: Timeframe) -> int:
        stmt = select(func.count()).select_from(Candle).where(
            Candle.symbol == symbol, Candle.timeframe == timeframe.value
        )
        return int(self.session.scalar(stmt) or 0)

    def first_timestamp(self, symbol: str, timeframe: Timeframe) -> datetime | None:
        stmt = (
            select(func.min(Candle.timestamp))
            .where(Candle.symbol == symbol, Candle.timeframe == timeframe.value)
        )
        return self.session.scalar(stmt)

    def last_timestamp(self, symbol: str, timeframe: Timeframe) -> datetime | None:
        stmt = (
            select(func.max(Candle.timestamp))
            .where(Candle.symbol == symbol, Candle.timeframe == timeframe.value)
        )
        return self.session.scalar(stmt)

    def has_gap(self, symbol: str, timeframe: Timeframe) -> bool:
        """True if the stored series has a hole.

        A gap silently changes every indicator that spans it, and a backtest
        over a gappy series looks fine while being meaningless. Worth detecting
        rather than assuming.
        """
        stamps = self.session.scalars(
            select(Candle.timestamp)
            .where(Candle.symbol == symbol, Candle.timeframe == timeframe.value)
            .order_by(Candle.timestamp)
        ).all()
        if len(stamps) < 2:
            return False
        expected = timeframe.seconds
        for previous, current in zip(stamps, stamps[1:], strict=False):
            delta = (current - previous).total_seconds()
            if delta > expected * 1.5:
                logger.warning(
                    "candle_gap_detected",
                    symbol=symbol,
                    timeframe=timeframe.value,
                    gap_seconds=delta,
                )
                return True
        return False

    def delete_range(self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime) -> int:
        result = self.session.execute(
            delete(Candle).where(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe.value,
                Candle.timestamp >= start,
                Candle.timestamp <= end,
            )
        )
        return int(result.rowcount or 0)