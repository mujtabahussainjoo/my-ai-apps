"""Reference data seeding.

Seeding is idempotent and deliberately minimal: the strategies and symbols the
loop needs to operate, plus the starting paper balance. It never fabricates
trades, metrics, or qualification - those come from real runs, which is the
whole point of the promotion gate.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.core.config import Settings, get_settings
from src.core.enums import StrategyStatus, TradingMode
from src.core.logging import get_logger
from src.database.repositories import PortfolioRepository, StrategyStatusRepository

logger = get_logger(__name__)

#: Every strategy starts CANDIDATE. Marking one QUALIFIED is a human decision
#: backed by the qualification report, never a side effect of seeding.
DEFAULT_STRATEGIES = ("breakout", "momentum", "ema_rsi_macd", "mean_reversion")

DEFAULT_SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT")


def ensure_reference_data(
    session: Session,
    settings: Settings | None = None,
    *,
    mode: str = TradingMode.PAPER.value,
) -> dict[str, int]:
    """Create any missing reference rows. Safe to run on every startup."""
    settings = settings or get_settings()
    statuses = StrategyStatusRepository(session)
    portfolio = PortfolioRepository(session)

    created = {"strategies": 0, "balances": 0}

    for name in (*DEFAULT_STRATEGIES, *settings.trading_strategies):
        if statuses.get(name) is None:
            statuses.set(
                name,
                StrategyStatus.CANDIDATE,
                qualified=False,
                blocking_reason="awaiting backtest and paper evidence",
            )
            created["strategies"] += 1

    if portfolio.get_balance("USDT", mode) is None:
        portfolio.set_balance("USDT", mode, settings.starting_equity_usd)
        created["balances"] += 1

    session.commit()
    logger.info("reference_data_seeded", **created)
    return created


def set_qualified(
    session: Session,
    strategy: str,
    *,
    qualified: bool,
    reason: str | None = None,
    metrics: dict | None = None,
    qualification: dict | None = None,
) -> StrategyStatus:
    """Promote or demote a strategy.

    Exposed as a function rather than a CLI flag on the seed script so that
    qualification always travels with a stated justification. ``metrics`` and
    ``qualification`` carry the evidence, so the numbers behind a promotion are
    readable later without having to find the run that justified it.
    """
    statuses = StrategyStatusRepository(session)
    statuses.set(
        strategy,
        StrategyStatus.QUALIFIED if qualified else StrategyStatus.CANDIDATE,
        qualified=qualified,
        metrics=metrics,
        qualification=qualification,
        blocking_reason=None if qualified else (reason or "revoked"),
    )
    session.commit()
    logger.info("strategy_status_changed", strategy=strategy, qualified=qualified, reason=reason)
    return StrategyStatus.QUALIFIED if qualified else StrategyStatus.CANDIDATE


__all__ = ["DEFAULT_STRATEGIES", "DEFAULT_SYMBOLS", "ensure_reference_data", "set_qualified"]
