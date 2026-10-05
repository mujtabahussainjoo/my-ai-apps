"""Hard risk limits and circuit breakers.

Three independent breakers, all of which must be released before trading
resumes:

- **Kill switch** — operator-controlled, process-wide.
- **Daily loss limit** — halts for the remainder of the UTC day.
- **Max drawdown** — halts until an operator resets it.

The daily counter resets on the UTC day boundary, not a rolling 24 hours,
because "losing 3% today" should mean the calendar day an operator is looking
at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from src.core.config import Settings
from src.core.logging import get_logger
from src.schemas.risk import CircuitBreakerState

logger = get_logger(__name__)


@dataclass(slots=True)
class LimitBreakers:
    """Mutable breaker state. Owned by the risk engine, inspected by the API."""

    daily_loss_halted: bool = False
    daily_loss_halt_date: date | None = None
    drawdown_halted: bool = False
    drawdown_halt_peak_equity: float = 0.0
    #: Rolling count of AI-proposed trades in the current UTC day.
    trades_today: int = 0
    trades_today_date: date | None = None
    halt_reasons: list[str] = field(default_factory=list)

    def reset_daily_if_needed(self, today: date | None = None) -> None:
        """Clear the day-scoped breakers when the UTC day rolls over.

        The drawdown breaker deliberately survives a day change: drawdown is
        measured from the equity peak, not from midnight.
        """
        current = today or datetime.now(timezone.utc).date()

        if self.trades_today_date != current:
            # A count with no stamp is assumed to belong to today rather than
            # being discarded: handing out a fresh budget is the unsafe
            # direction to be wrong in.
            if self.trades_today and self.trades_today_date is not None:
                logger.info(
                    "trade_budget_reset",
                    previous_day=str(self.trades_today_date),
                    new_day=str(current),
                    previous_count=self.trades_today,
                )
                self.trades_today = 0
            self.trades_today_date = current

        if self.daily_loss_halt_date != current:
            if self.daily_loss_halted:
                logger.info("daily_loss_halt_cleared", new_date=str(current))
            self.daily_loss_halted = False
            self.daily_loss_halt_date = current
            self.halt_reasons = [r for r in self.halt_reasons if "daily loss" not in r.lower()]

    def engage_daily_loss(self, reason: str) -> None:
        self.daily_loss_halted = True
        self.daily_loss_halt_date = datetime.now(timezone.utc).date()
        self.halt_reasons.append(reason)
        logger.warning("circuit_breaker_daily_loss", reason=reason)

    def engage_drawdown(self, reason: str, peak_equity: float) -> None:
        self.drawdown_halted = True
        self.drawdown_halt_peak_equity = peak_equity
        self.halt_reasons.append(reason)
        logger.warning("circuit_breaker_drawdown", reason=reason, peak_equity=peak_equity)

    def reset_drawdown(self, *, operator: str) -> None:
        logger.info("circuit_breaker_drawdown_reset", operator=operator)
        self.drawdown_halted = False
        self.drawdown_halt_peak_equity = 0.0
        self.halt_reasons = [r for r in self.halt_reasons if "drawdown" not in r.lower()]

    def record_trade(self) -> None:
        self.reset_daily_if_needed()
        self.trades_today += 1

    def status(self, settings: Settings, equity: float, daily_pnl: float, drawdown_pct: float) -> CircuitBreakerState:
        from src.core.security import kill_switch

        self.reset_daily_if_needed()
        daily_limit_usd = equity * settings.risk_daily_loss_limit_pct / 100
        return CircuitBreakerState(
            kill_switch_engaged=kill_switch.engaged,
            kill_switch_reason=kill_switch.reason,
            daily_loss_halted=self.daily_loss_halted,
            drawdown_halted=self.drawdown_halted,
            trading_enabled=not (
                kill_switch.engaged or self.daily_loss_halted or self.drawdown_halted
            ),
            halt_reason="; ".join(self.halt_reasons) or None,
            daily_pnl_usd=round(daily_pnl, 2),
            daily_loss_limit_usd=round(daily_limit_usd, 2),
            current_drawdown_pct=round(drawdown_pct, 3),
            max_drawdown_pct=settings.risk_max_drawdown_pct,
        )


def validate_daily_loss(
    *,
    settings: Settings,
    breakers: LimitBreakers,
    equity_usd: float,
    daily_pnl_usd: float,
) -> str | None:
    """Return a halt reason if the daily loss limit is breached."""
    breakers.reset_daily_if_needed()
    if breakers.daily_loss_halted:
        return "daily loss limit already engaged for this UTC day"

    limit_usd = equity_usd * settings.risk_daily_loss_limit_pct / 100
    if limit_usd <= 0:
        return None
    if daily_pnl_usd <= -limit_usd:
        reason = (
            f"daily loss ${abs(daily_pnl_usd):,.2f} reached the "
            f"{settings.risk_daily_loss_limit_pct}% limit "
            f"(${limit_usd:,.2f}) — trading halted until 00:00 UTC"
        )
        breakers.engage_daily_loss(reason)
        return reason
    return None


def validate_drawdown(
    *,
    settings: Settings,
    breakers: LimitBreakers,
    peak_equity_usd: float,
    current_equity_usd: float,
) -> str | None:
    """Return a halt reason if max drawdown is breached."""
    if breakers.drawdown_halted:
        return "max drawdown breaker engaged — manual reset required"

    if peak_equity_usd <= 0 or current_equity_usd <= 0:
        return None

    drawdown_pct = (peak_equity_usd - current_equity_usd) / peak_equity_usd * 100
    if drawdown_pct >= settings.risk_max_drawdown_pct:
        reason = (
            f"drawdown {drawdown_pct:.2f}% reached the "
            f"{settings.risk_max_drawdown_pct}% limit "
            f"(${peak_equity_usd:,.2f} -> ${current_equity_usd:,.2f}) — "
            f"manual reset required"
        )
        breakers.engage_drawdown(reason, peak_equity_usd)
        return reason
    return None


def validate_daily_trade_count(breakers: LimitBreakers, max_trades: int) -> str | None:
    """Bound how much the autonomous pipeline may do in one day."""
    breakers.reset_daily_if_needed()
    if breakers.trades_today >= max_trades:
        return f"daily AI trade budget exhausted: {breakers.trades_today}/{max_trades}"
    return None