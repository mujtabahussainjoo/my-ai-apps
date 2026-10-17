"""Trading layer: brokers plus the risk-gated executor.

Layout follows ``Framework.md``: :mod:`trading.paper`, :mod:`trading.live` and
:mod:`trading.testnet` hold the venue adapters, while the gate that decides
whether an order may be sent at all lives in :mod:`trading.executor`.
"""

from src.trading.base import (
    Broker,
    ExecutionInstruction,
    FillReport,
    PositionExit,
    fee_for,
    fill_price_for,
    is_limit,
    side_value,
)
from src.trading.executor import (
    ExecutionOutcome,
    ExecutionRejected,
    ExecutorConfig,
    OrderExecutor,
    build_paper_executor,
)
from src.trading.live.broker import ExchangeBroker
from src.trading.paper.broker import PaperBroker

__all__ = [
    "Broker",
    "ExchangeBroker",
    "ExecutionInstruction",
    "ExecutionOutcome",
    "ExecutionRejected",
    "ExecutorConfig",
    "FillReport",
    "OrderExecutor",
    "PaperBroker",
    "PositionExit",
    "build_paper_executor",
    "fee_for",
    "fill_price_for",
    "is_limit",
    "side_value",
]
