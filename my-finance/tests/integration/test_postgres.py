"""Guarantees that only real PostgreSQL can provide.

SQLite stores NUMERIC columns as REAL, so the unit suite cannot prove exact
decimal arithmetic or JSONB behaviour. These tests run against the Compose
Postgres service and skip cleanly when it is not reachable.
"""

from __future__ import annotations

import os
from decimal import Decimal

import pytest
import sqlalchemy as sa
from src.core.enums import OrderSide, OrderType
from src.database.base import Base, new_id
from src.database.migrations import discover, upgrade
from src.database.repositories import OrderRepository
from src.database.session import build_engine
from src.schemas.order import Order, OrderFill

URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine() -> sa.Engine:
    if not URL:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    candidate = sa.create_engine(URL, pool_pre_ping=True, connect_args={"connect_timeout": 3})
    try:
        with candidate.connect() as conn:
            conn.execute(sa.text("select 1"))
    except Exception as exc:  # noqa: BLE001 - any failure means "not available"
        pytest.skip(f"PostgreSQL unavailable ({type(exc).__name__}), skipping integration tests")
    build_engine(URL).dispose()
    return candidate


@pytest.fixture(scope="module", autouse=True)
def schema(engine: sa.Engine) -> None:
    upgrade(engine)


@pytest.fixture
def session(engine: sa.Engine):
    connection = engine.connect()
    transaction = connection.begin()
    yield sa.orm.Session(bind=connection, join_transaction_mode="create_savepoint")
    transaction.rollback()
    connection.close()


def test_migrations_are_idempotent(engine: sa.Engine) -> None:
    """Re-running must apply nothing and leave exactly one version row."""
    assert upgrade(engine) == []
    with engine.connect() as conn:
        versions = conn.execute(sa.text("select version from schema_migrations")).scalars().all()
    assert sorted(versions) == [m.version for m in discover()]


def test_money_columns_are_true_numeric(engine: sa.Engine) -> None:
    """Guards against a future refactor silently downgrading to FLOAT."""
    money = ("entry_price", "exit_price", "pnl_usd", "fees_usd", "gross_pnl_usd")
    with engine.connect() as conn:
        types = dict(
            conn.execute(
                sa.text(
                    "select column_name, data_type from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'trades'"
                )
            ).all()
        )
    for column in money:
        assert types[column] == "numeric", f"trades.{column} is {types[column]}, expected numeric"


def test_json_columns_use_jsonb(engine: sa.Engine) -> None:
    with engine.connect() as conn:
        types = dict(
            conn.execute(
                sa.text(
                    "select column_name, data_type from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'risk_assessments' "
                    "and data_type = 'jsonb'"
                )
            ).all()
        )
    assert types, "no JSONB columns found on risk_assessments"


def test_decimal_arithmetic_is_exact(session) -> None:
    """The identity SQLite cannot honour: 0.1 + 0.2 must equal 0.3 exactly."""
    repo = OrderRepository(session)
    order_id = new_id()
    repo.create(
        Order(
            id=order_id,
            client_order_id=new_id(),
            symbol="BTC/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            status="pending",
            quantity=Decimal("0.3"),
        )
    )
    for quantity in ("0.1", "0.2"):
        repo.apply_fill(
            OrderFill(
                order_id=order_id,
                quantity=Decimal(quantity),
                price=Decimal("100.5"),
                fee_usd=Decimal("0.01"),
            )
        )
    session.flush()

    row = repo.get(order_id)
    assert row.quantity == Decimal("0.3000000000")
    assert row.filled_quantity == Decimal("0.3000000000")
    assert row.filled_quantity == row.quantity


def test_partial_fractional_fills_accumulate_exactly(session) -> None:
    repo = OrderRepository(session)
    order_id = new_id()
    repo.create(
        Order(
            id=order_id,
            client_order_id=new_id(),
            symbol="ETH/USDT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            status="pending",
            quantity=Decimal("1.7"),
        )
    )
    for quantity in ("0.3", "0.3", "0.3", "0.3", "0.5"):
        repo.apply_fill(
            OrderFill(
                order_id=order_id,
                quantity=Decimal(quantity),
                price=Decimal("2000"),
                fee_usd=Decimal("0.05"),
            )
        )
    session.flush()
    assert repo.get(order_id).filled_quantity == Decimal("1.7000000000")


def test_overfill_constraint_fires_on_real_numeric(session) -> None:
    repo = OrderRepository(session)
    order_id = new_id()
    repo.create(
        Order(
            id=order_id,
            client_order_id=new_id(),
            symbol="SOL/USDT",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            status="pending",
            quantity=Decimal("1"),
        )
    )
    with pytest.raises(ValueError, match="over-fill"):
        repo.apply_fill(OrderFill(order_id=order_id, quantity=Decimal("1.5"), price=Decimal("10"), fee_usd=0))


def test_every_table_exists(engine: sa.Engine) -> None:
    """The 22-table schema from Framework.md must be fully materialised."""
    expected = set(Base.metadata.tables)
    with engine.connect() as conn:
        actual = set(
            conn.execute(
                sa.text(
                    "select table_name from information_schema.tables "
                    "where table_schema = 'public' and table_type = 'BASE TABLE'"
                )
            ).scalars()
        )
    missing = expected - actual - {"schema_migrations"}
    assert not missing, f"missing tables: {sorted(missing)}"


def test_upgrade_existing_signal_and_strategy_constraints(engine):
    from src.database.migrations import v004_signal_lifecycle, v005_strategy_lifecycle, v006_signal_claims

    # Simulate a pre-lifecycle schema in a rollback-only transaction, leaving
    # the shared disposable database intact for the remaining checks.
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            for column in ("status", "processed_at", "order_id", "reject_reason"):
                conn.exec_driver_sql(f"ALTER TABLE signals DROP COLUMN {column} CASCADE")
            v004_signal_lifecycle.upgrade(conn)
            v005_strategy_lifecycle.downgrade(conn)
            v005_strategy_lifecycle.upgrade(conn)
            v006_signal_claims.upgrade(conn)
            signal_checks = sa.inspect(conn).get_check_constraints("signals")
            strategy_checks = sa.inspect(conn).get_check_constraints("strategy_status")
            lifecycle = [c for c in signal_checks if "status" in c["sqltext"]]
            stages = [c for c in strategy_checks if "status" in c["sqltext"]]
            assert len(lifecycle) == 1 and "processing" in lifecycle[0]["sqltext"]
            assert len(stages) == 1 and "paper_testing" in stages[0]["sqltext"]
        finally:
            transaction.rollback()
