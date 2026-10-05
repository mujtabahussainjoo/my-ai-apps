"""Prometheus metrics, rendered from live database state.

No ``prometheus_client`` dependency: the exposition format is a few lines of
text, and adding a dependency to report ten numbers would be a poor trade.

What is exported is deliberately narrow - equity, exposure, position count,
signals waiting or declined, and how much drawdown the account is carrying.
Nothing here is a secret, and nothing here reveals a position's size beyond the
aggregate. ``/metrics`` is unauthenticated because a scraper cannot send
credentials, so if this route ever needed to expose something sensitive the
answer would be a second, authenticated route rather than a token here.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from src.core.enums import OrderStatus
from src.core.logging import get_logger
from src.database.models.trading import Order, Position, Signal
from src.schemas.base import utcnow

from apps.api.dependencies import SessionDep, SettingsDep

router = APIRouter(tags=["metrics"])
logger = get_logger(__name__)

#: Lookback for the rejection rate. Long enough to mean something, short enough
#: that a bad afternoon is visible before the weekend.
REJECTION_WINDOW = timedelta(hours=24)


@router.get(
    "/metrics",
    include_in_schema=False,
    # Without this FastAPI serialises the body as a JSON string, and a scraper
    # fed a quoted, escaped blob parses nothing at all.
    response_class=PlainTextResponse,
    responses={200: {"content": {"text/plain": {}}}},
)
def metrics(session: SessionDep, settings: SettingsDep) -> str:
    """Render the current state in Prometheus exposition format."""
    mode = settings.trading_mode

    equity = _equity(session, mode)
    if equity is None:
        # No snapshot yet is a normal state on a fresh database. Reporting the
        # service as down would page someone about a deployment that just
        # started, so this is reported as its own series instead.
        return _render({}, has_snapshot=False, mode=mode)

    exposure = session.scalar(
        select(func.coalesce(func.sum(Position.quantity * Position.entry_price), 0.0)).where(
            Position.mode == mode
        )
    )
    positions = session.scalar(select(func.count()).select_from(Position).where(Position.mode == mode))
    open_orders = session.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.mode == mode, Order.status.in_([OrderStatus.PENDING.value, OrderStatus.OPEN.value]))
    )
    since = utcnow() - REJECTION_WINDOW
    signals_recent = session.scalar(
        select(func.count()).select_from(Signal).where(Signal.created_at >= since)
    )
    signals_rejected = session.scalar(
        select(func.count())
        .select_from(Signal)
        .where(Signal.created_at >= since, Signal.status == "rejected")
    )
    signals_pending = session.scalar(
        select(func.count()).select_from(Signal).where(Signal.status == "pending")
    )
    positions_closed = session.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.mode == mode, Order.status == OrderStatus.FILLED.value)
    )

    gauges = {
        "equity_usd": (equity, "Account equity"),
        "exposure_usd": (float(exposure or 0.0), "Gross notional of open positions"),
        "open_positions": (float(positions or 0), "Count of open positions"),
        "open_orders": (float(open_orders or 0), "Orders awaiting a fill"),
        "filled_orders": (float(positions_closed or 0), "Orders filled to date"),
        "exposure_ratio": (
            float(exposure or 0.0) / equity if equity else 0.0,
            "Exposure divided by equity",
        ),
        "signals_pending": (float(signals_pending or 0), "Signals waiting to be evaluated"),
        "signals_24h": (float(signals_recent or 0), "Signals recorded in the last 24h"),
        "signals_rejected_24h": (
            float(signals_rejected or 0),
            "Signals the risk engine declined in the last 24h",
        ),
        "signal_rejection_ratio_24h": (
            float(signals_rejected or 0) / float(signals_recent) if signals_recent else 0.0,
            "Share of recent signals declined",
        ),
    }
    return _render(gauges, has_snapshot=True, mode=mode)


def _equity(session: SessionDep, mode: str) -> float | None:
    from src.database.repositories import PortfolioRepository

    snapshot = PortfolioRepository(session).latest_snapshot(mode)
    return float(snapshot.equity_usd) if snapshot else None


def _render(
    gauges: dict[str, tuple[float, str]],
    *,
    has_snapshot: bool,
    mode: str | None = None,
) -> str:
    out: list[str] = []
    for name, (value, help_text) in gauges.items():
        out.append(f"# HELP financ_{name} {help_text}")
        out.append(f"# TYPE financ_{name} gauge")
        out.append(f"financ_{name} {value:g}")

    # Two separate facts. "up" is about the endpoint answering at all, which it
    # just did; a missing snapshot is reported on its own series so an alert
    # can distinguish "the service is broken" from "nothing has traded yet".
    out.append("# HELP financ_up Whether the metrics endpoint could collect state")
    out.append("# TYPE financ_up gauge")
    out.append("financ_up 1")

    out.append("# HELP financ_has_snapshot Whether a portfolio snapshot exists")
    out.append("# TYPE financ_has_snapshot gauge")
    out.append(f"financ_has_snapshot {1 if has_snapshot else 0}")

    if mode:
        out.append("# HELP financ_trading_mode_active Whether live trading is enabled")
        out.append("# TYPE financ_trading_mode_active gauge")
        out.append(f"financ_trading_mode_active {1 if mode == 'live' else 0}")

    return "\n".join(out) + "\n"