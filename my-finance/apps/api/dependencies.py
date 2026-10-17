"""Shared FastAPI dependencies.

Two rules shape this module:

1. Read routes are open (the dashboard needs them), but anything that can move
   money or change a strategy's standing requires a key.
2. A qualification change is the most dangerous thing this API can do, so it is
   separated behind its own dependency with its own reason field. Seeding and
   qualification must never be the same click.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session
from src.core.config import Settings, get_settings
from src.database.repositories import (
    ApprovalRepository,
    BacktestRepository,
    CandleRepository,
    OrderRepository,
    PaperPerformanceRepository,
    PortfolioRepository,
    RiskRepository,
    SignalRepository,
    StrategyStatusRepository,
    SystemEventRepository,
    TradeRepository,
)
from src.database.session import build_engine
from src.risk.risk_engine import RiskEngine

_settings = get_settings()

# One engine for the process. Building a new engine per request would open a new
# connection pool on every call and quietly exhaust Postgres' connections.
_engine = build_engine()


def get_settings_dep() -> Settings:
    return _settings


def get_session() -> Iterator[Session]:
    """A session per request, rolled back on any error."""
    session = Session(_engine, expire_on_commit=False)
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]


# ── Repository providers ────────────────────────────────────────────────────


def get_candles(session: SessionDep) -> CandleRepository:
    return CandleRepository(session)


def get_signals(session: SessionDep) -> SignalRepository:
    return SignalRepository(session)


def get_orders(session: SessionDep) -> OrderRepository:
    return OrderRepository(session)


def get_trades(session: SessionDep) -> TradeRepository:
    return TradeRepository(session)


def get_portfolio(session: SessionDep) -> PortfolioRepository:
    return PortfolioRepository(session)


def get_risk(session: SessionDep) -> RiskRepository:
    return RiskRepository(session)


def get_strategies(session: SessionDep) -> StrategyStatusRepository:
    return StrategyStatusRepository(session)


def get_backtests(session: SessionDep) -> BacktestRepository:
    return BacktestRepository(session)


def get_paper_performance(session: SessionDep) -> PaperPerformanceRepository:
    return PaperPerformanceRepository(session)


def get_events(session: SessionDep) -> SystemEventRepository:
    return SystemEventRepository(session)


def get_approvals(session: SessionDep) -> ApprovalRepository:
    return ApprovalRepository(session)


def get_risk_engine(settings: SettingsDep, session: SessionDep) -> RiskEngine:
    return RiskEngine(settings)


CandlesDep = Annotated[CandleRepository, Depends(get_candles)]
SignalsDep = Annotated[SignalRepository, Depends(get_signals)]
OrdersDep = Annotated[OrderRepository, Depends(get_orders)]
TradesDep = Annotated[TradeRepository, Depends(get_trades)]
PortfolioDep = Annotated[PortfolioRepository, Depends(get_portfolio)]
RiskDep = Annotated[RiskRepository, Depends(get_risk)]
StrategiesDep = Annotated[StrategyStatusRepository, Depends(get_strategies)]
BacktestsDep = Annotated[BacktestRepository, Depends(get_backtests)]
PaperPerformanceDep = Annotated[PaperPerformanceRepository, Depends(get_paper_performance)]
EventsDep = Annotated[SystemEventRepository, Depends(get_events)]
ApprovalsDep = Annotated[ApprovalRepository, Depends(get_approvals)]
RiskEngineDep = Annotated[RiskEngine, Depends(get_risk_engine)]


# ── Authentication ──────────────────────────────────────────────────────────


def require_api_key(
    settings: SettingsDep,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """Gate a mutating route.

    If no key is configured the route refuses itself rather than defaulting
    open - an unauthenticated write path into a trading system is exactly the
    thing that must not happen by accident.
    """
    expected = settings.api_key.get_secret_value() if settings.api_key else None
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "API_KEY is not configured, so mutating endpoints are disabled. Set API_KEY to enable them."
            ),
        )
    if not x_api_key or not _constant_time_equals(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="a valid X-API-Key header is required",
        )


def require_operator(
    settings: SettingsDep,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    x_operator: Annotated[str | None, Header(alias="X-Operator")] = None,
) -> str:
    """A stricter gate for changes to a strategy's standing.

    Requiring a named operator means every qualification is attributable to a
    person, which is what makes the promotion trail auditable.
    """
    require_api_key(settings, x_api_key)
    if not x_operator or not x_operator.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Operator is required so the change can be attributed to a person",
        )
    return x_operator.strip()


def _constant_time_equals(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a.encode(), b.encode())


ApiKeyDep = Annotated[None, Depends(require_api_key)]
OperatorDep = Annotated[str, Depends(require_operator)]
