"""All table definitions.

Importing this package registers every mapper with ``Base.metadata``, which is
what ``create_all`` and the migration runner rely on. Import the modules
directly if you only need one domain.
"""

from src.database.base import Base
from src.database.models.audit import (
    AgentMessage,
    AgentSession,
    BacktestRun,
    BacktestTrade,
    CircuitBreakerEvent,
    RiskAssessment,
    RiskEvent,
    StrategyStatus,
    SystemEvent,
)
from src.database.models.market import Candle, Symbol, TickerSnapshot
from src.database.models.trading import (
    Approval,
    Balance,
    Order,
    OrderFill,
    PaperPerformance,
    PortfolioSnapshot,
    Position,
    Signal,
    Trade,
    Volume24h,
)

__all__ = [
    "AgentMessage",
    "AgentSession",
    "Approval",
    "BacktestRun",
    "BacktestTrade",
    "Balance",
    "Base",
    "Candle",
    "CircuitBreakerEvent",
    "Order",
    "OrderFill",
    "PaperPerformance",
    "PortfolioSnapshot",
    "Position",
    "RiskAssessment",
    "RiskEvent",
    "Signal",
    "StrategyStatus",
    "Symbol",
    "SystemEvent",
    "TickerSnapshot",
    "Trade",
    "Volume24h",
]
