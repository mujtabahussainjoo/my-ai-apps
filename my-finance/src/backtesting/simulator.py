"""Fill simulation: fees, slippage, and intrabar stop/target resolution.

The honesty of every performance number in this system depends on this module.
Three choices matter:

1. **Fees and slippage are charged on both legs.** A backtest that omits the
   exit cost inflates every result.
2. **Stops fill at the stop price, never better.** Optimistically filling a
   stop at the close, or assuming no gap through it, is the single most common
   way a backtest lies.
3. **If a bar touches both the stop and the target, the stop wins.** Real
   intrabar sequencing is unknowable from OHLCV; assuming the favourable leg is
   a fabricated edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from src.core.config import Settings, get_settings
from src.schemas.market import Candle
from src.schemas.trade import ExitReason


@dataclass(slots=True)
class Fill:
    """A simulated execution."""

    price: float
    fee_usd: float
    slippage_bps: float
    is_rejection: bool = False
    reason: str | None = None


@dataclass(slots=True)
class ExitDecision:
    """Result of checking whether an open position should close this bar."""

    should_exit: bool
    price: float | None = None
    reason: ExitReason | None = None
    note: str | None = None


def round_down(value: float, decimals: int = 8) -> float:
    """Round toward zero.

    Rounding quantity *down* means the simulator never assumes more size than
    the wallet paid for, which keeps the P&L arithmetic exactly consistent with
    the cash balance.
    """
    quantised = Decimal(str(value)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_DOWN)
    return float(quantised)


class FillSimulator:
    """Applies fees and slippage in the direction that hurts."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    @property
    def fee_rate(self) -> float:
        return self.settings.taker_fee_rate

    @property
    def slippage_rate(self) -> float:
        return self.settings.slippage_rate

    def simulate_market_fill(self, side: str, price: float, quantity: float) -> Fill:
        """Market order: slippage always moves the fill against the trader."""
        adverse = 1 + self.slippage_rate if side == "buy" else 1 - self.slippage_rate
        fill_price = round(price * adverse, 8)
        notional = fill_price * quantity
        return Fill(
            price=fill_price,
            fee_usd=notional * self.fee_rate,
            slippage_bps=self.slippage_rate * 10_000,
        )

    def simulate_limit_fill(self, side: str, limit_price: float, quantity: float) -> Fill:
        """Limit order: no slippage when it fills, which is the intent of a limit."""
        notional = limit_price * quantity
        return Fill(
            price=round(limit_price, 8),
            fee_usd=notional * self.fee_rate,
            slippage_bps=0.0,
        )

    def check_exit(
        self,
        candle: Candle,
        *,
        side: str,
        stop_loss: float | None,
        take_profit: float | None,
    ) -> ExitDecision:
        """Decide whether a position closes on this bar.

        Order of checks is the pessimistic convention: stop is evaluated
        before target whenever the bar's range spans both.
        """
        if side == "buy":
            stop_hit = stop_loss is not None and candle.low <= stop_loss
            target_hit = take_profit is not None and candle.high >= take_profit
        else:
            stop_hit = stop_loss is not None and candle.high >= stop_loss
            target_hit = take_profit is not None and candle.low <= take_profit

        if stop_hit and target_hit:
            # Ambiguous bar. Assume the worst case.
            price = stop_loss if stop_loss is not None else candle.close
            return ExitDecision(
                should_exit=True,
                price=price,
                reason="stop_loss",
                note="bar spanned both stop and target; stop assumed first (pessimistic)",
            )
        if stop_hit:
            return ExitDecision(
                should_exit=True,
                price=stop_loss,
                reason="stop_loss",
                note="stop filled at the stop price, never better",
            )
        if target_hit:
            return ExitDecision(should_exit=True, price=take_profit, reason="take_profit")
        return ExitDecision(should_exit=False)
