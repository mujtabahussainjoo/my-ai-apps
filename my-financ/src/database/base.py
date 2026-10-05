"""Declarative base for every table.

Three conventions hold throughout:

* **Money and quantity are ``NUMERIC``, never ``FLOAT``.** The domain schemas
  use floats, but a persisted ledger is the one place a rounding error becomes
  permanent and unauditable. ``sum(pnl_usd)`` must be exactly right years later.
* **Timestamps are timezone-aware and stored in UTC.** A naive timestamp in a
  ledger is a bug waiting for a DST boundary or a container with a different
  ``TZ``.
* **Identifiers are application-generated UUIDs.** The database never hands out
  an id for a row that may need to be written before the insert completes, and
  replay protection depends on the id being known client-side.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON, Numeric

#: JSONB on Postgres (indexable, binary), plain JSON elsewhere. The offline test
#: suite runs on SQLite, and a hard dependency on a Postgres dialect would make
#: the schema untestable without a live server.
JSONType = JSON().with_variant(JSONB, "postgresql")

#: Money and quantity types.
#:
#: On Postgres these are true ``NUMERIC`` columns, so sums and comparisons are
#: exact. SQLite has no Decimal type at all - SQLAlchemy binds Decimal as a
#: float - so on SQLite they are floats. Two consequences, both deliberate:
#:
#: * CHECK constraints on money columns cannot be tested for bit-exactness on
#:   SQLite. The ledger identity is therefore written as a 1e-6 comparison, and
#:   the exact case is covered by the Postgres integration test instead.
#: * ``tests/integration/`` runs the numeric suite against a real Postgres,
#:   which is the only place exactness is actually guaranteed.
MONEY = Numeric(20, 8)
#: Alias used by the ``*_usd`` columns, so the name at the call site matches
#: the name at the schema.
USD = MONEY
PRICE = Numeric(24, 10)
QUANTITY = Numeric(24, 10)
VOLUME = Numeric(32, 8)


#: SQLite only auto-increments a column declared exactly ``INTEGER PRIMARY
#: KEY``; a BIGINT primary key must be given an explicit value. Without this
#: variant every autoincremented table fails on SQLite with NOT NULL.
BIGINT_PK = BigInteger().with_variant(Integer, "sqlite")

#: Explicit constraint names. Without this, Postgres auto-names constraints and
#: an ``ALTER`` in a migration cannot refer to one.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        nullable=False,
    )
