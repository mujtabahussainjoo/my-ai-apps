"""Portfolio and performance schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from src.core.enums import OrderSide, TradingMode
from src.schemas.base import Base, NonNegativeFloat, Price, utcnow


class Balance(Base):
    asset: str
    free: NonNegativeFloat
    locked: NonNegativeFloat = 0.0

    @property
    def total(self) -> float:
        return self.free + self.locked


class Position(Base):
    """An open position.

    Lives in the portfolio domain, not the market-data domain: a position is a
    fact about *this account's* book, while :class:`Ticker` is a fact about the
    exchange. Keeping them apart stops an exchange payload from ever being
    mistaken for account state.
    """

    symbol: str
    quantity: NonNegativeFloat
    entry_price: Price
    side: OrderSide = OrderSide.BUY
    current_price: Price | None = None
    stop_loss: Price | None = None
    take_profit: Price | None = None
    strategy: str | None = None
    mode: TradingMode = TradingMode.PAPER
    entry_fee_usd: NonNegativeFloat = 0.0
    opened_at: datetime = Field(default_factory=utcnow)

    @property
    def is_long(self) -> bool:
        return self.side is OrderSide.BUY

    @property
    def market_price(self) -> float:
        return self.current_price or self.entry_price

    @property
    def notional_usd(self) -> float:
        return self.quantity * self.market_price

    @property
    def cost_basis_usd(self) -> float:
        return self.quantity * self.entry_price

    @property
    def unrealized_pnl_usd(self) -> float:
        direction = 1.0 if self.is_long else -1.0
        return direction * (self.market_price - self.entry_price) * self.quantity - self.entry_fee_usd

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.cost_basis_usd == 0:
            return 0.0
        return self.unrealized_pnl_usd / self.cost_basis_usd * 100

    @property
    def open_risk_usd(self) -> float:
        """Cash still at risk if the stop is hit.

        Zero for a position with no stop, which is exactly why an order without
        a stop is rejected upstream rather than sized here.
        """
        if self.stop_loss is None:
            return 0.0
        return abs(self.market_price - self.stop_loss) * self.quantity

    @property
    def stop_distance_pct(self) -> float:
        if self.stop_loss is None or self.entry_price == 0:
            return 0.0
        return abs(self.entry_price - self.stop_loss) / self.entry_price * 100


class PortfolioSnapshot(Base):
    """Point-in-time portfolio state used by the risk engine.

    The risk engine only ever sees this object, never the database directly, so
    its inputs are explicit and testable.
    """

    equity_usd: NonNegativeFloat
    cash_usd: NonNegativeFloat
    positions_value_usd: NonNegativeFloat = 0.0
    unrealized_pnl_usd: float = 0.0
    realized_pnl_usd: float = 0.0
    daily_pnl_usd: float = 0.0
    daily_pnl_pct: float = 0.0
    total_exposure_usd: NonNegativeFloat = 0.0
    exposure_pct: float = Field(default=0.0, ge=0)
    open_positions: int = Field(default=0, ge=0)
    current_drawdown_pct: float = Field(default=0.0, ge=0)
    peak_equity_usd: NonNegativeFloat = 0.0
    starting_equity_usd: NonNegativeFloat = 0.0
    mode: TradingMode = TradingMode.PAPER
    as_of: datetime = Field(default_factory=utcnow)
    #: Open positions, when the caller has them. The aggregate fields above stay
    #: authoritative for capital totals; this list drives per-symbol and
    #: open-risk questions the totals cannot answer.
    positions: list[Position] = Field(default_factory=list)

    @property
    def open_risk_usd(self) -> float:
        """Sum of cash-at-risk across open positions, if tracked."""
        return sum(position.open_risk_usd for position in self.positions)

    def position_exposure_usd(self, symbol: str) -> float:
        return sum(
            position.notional_usd for position in self.positions if position.symbol == symbol
        )

    @property
    def open_risk_pct(self) -> float:
        if self.equity_usd == 0:
            return 0.0
        return self.open_risk_usd / self.equity_usd * 100


class PerformanceMetrics(Base):
    """Full metric set for a strategy or portfolio over a window.

    Every field here is derived from closed trades by
    :mod:`src.evaluation.metrics`; nothing is estimated.
    """

    total_trades: int = Field(default=0, ge=0)
    winning_trades: int = Field(default=0, ge=0)
    losing_trades: int = Field(default=0, ge=0)
    breakeven_trades: int = Field(default=0, ge=0)

    win_rate: float = Field(default=0.0, ge=0, le=1)
    profit_factor: float = 0.0
    expectancy_usd: float = 0.0
    expectancy_r: float = 0.0

    net_profit_usd: float = 0.0
    net_profit_pct: float = 0.0
    gross_profit_usd: float = 0.0
    gross_loss_usd: float = 0.0
    total_fees_usd: float = Field(default=0.0, ge=0)

    average_win_usd: float = 0.0
    average_loss_usd: float = 0.0
    payoff_ratio: float = 0.0
    largest_win_usd: float = 0.0
    largest_loss_usd: float = 0.0

    max_drawdown_pct: float = Field(default=0.0, ge=0)
    max_drawdown_usd: float = Field(default=0.0, ge=0)
    max_consecutive_losses: int = Field(default=0, ge=0)
    max_consecutive_wins: int = Field(default=0, ge=0)

    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    #: Mean *realised* R-multiple per trade.
    average_risk_reward: float = 0.0
    #: Mean *planned* reward-to-risk of the signals that produced these trades.
    #: This is what the qualification gate's "R/R >= 1:2" rule refers to.
    planned_risk_reward: float = 0.0
    average_trade_duration_seconds: float = 0.0

    recovery_factor: float = 0.0
    equity_curve: list[float] = Field(default_factory=list)
    computed_at: datetime = Field(default_factory=utcnow)
    sample_size_warning: str | None = None

    @property
    def has_adequate_sample(self) -> bool:
        return self.total_trades >= 100