"""Repositories.

The pattern throughout: take a ``Session`` in the constructor, never open one.
Transaction boundaries belong to the caller, so a workflow that must write an
order, its risk assessment and its trade atomically can do so in one
transaction.
"""

from src.database.repositories.candle_repo import CandleRepository
from src.database.repositories.portfolio_repo import (
    PaperPerformanceRepository,
    PortfolioRepository,
)
from src.database.repositories.risk_repo import (
    BacktestRepository,
    RiskRepository,
    StrategyStatusRepository,
    SystemEventRepository,
)
from src.database.repositories.signal_repo import SignalRepository
from src.database.repositories.trading_repo import (
    ApprovalRepository,
    OrderRepository,
    TradeRepository,
)

__all__ = [
    "ApprovalRepository",
    "BacktestRepository",
    "CandleRepository",
    "OrderRepository",
    "PaperPerformanceRepository",
    "PortfolioRepository",
    "RiskRepository",
    "SignalRepository",
    "StrategyStatusRepository",
    "SystemEventRepository",
    "TradeRepository",
]