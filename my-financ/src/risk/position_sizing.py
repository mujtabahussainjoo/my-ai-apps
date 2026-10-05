"""Position sizing.

Fixed-fractional risk sizing, then three independent caps. The order matters:
the *smallest* of the caps always wins, so no single generous limit can
override a tighter one.
"""

from __future__ import annotations

from src.core.logging import get_logger
from src.schemas.risk import PositionSizeRequest, PositionSizeResult

logger = get_logger(__name__)


class PositionSizer:
    """Computes quantity from a risk budget, subject to caps."""

    def __init__(
        self,
        *,
        max_position_pct: float,
        max_risk_per_trade_pct: float,
        max_notional_usd: float = 50_000.0,
        min_notional_usd: float = 10.0,
    ) -> None:
        self.max_position_pct = max_position_pct
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.max_notional_usd = max_notional_usd
        self.min_notional_usd = min_notional_usd

    def calculate(self, request: PositionSizeRequest) -> PositionSizeResult | None:
        """Return the sized position, or ``None`` if it is not tradeable.

        ``None`` is returned rather than a zero quantity so callers must handle
        the rejection explicitly instead of placing a 0-size order.
        """
        stop_distance = abs(request.entry_price - request.stop_loss)
        if stop_distance <= 0:
            logger.warning("sizing_rejected", reason="stop_loss_equals_entry")
            return None

        stop_distance_pct = stop_distance / request.entry_price * 100

        # 1. Risk budget: how much we are willing to lose if the stop hits.
        # The tightest of the caller's budget and the engine's own limit wins;
        # `candidates` below records whichever cap actually bound the result.
        if request.max_risk_usd is not None:
            risk_budget = min(
                request.max_risk_usd,
                request.equity_usd * self.max_risk_per_trade_pct / 100,
            )
        elif request.risk_pct is not None:
            risk_budget = request.equity_usd * min(
                request.risk_pct, self.max_risk_per_trade_pct
            ) / 100
        else:
            risk_budget = request.equity_usd * self.max_risk_per_trade_pct / 100

        quantity_by_risk = risk_budget / stop_distance

        # 2. Position-value cap.
        position_pct = request.max_position_pct or self.max_position_pct
        position_pct = min(position_pct, self.max_position_pct)
        quantity_by_value = (request.equity_usd * position_pct / 100) / request.entry_price

        # 3. Absolute notional ceiling.
        quantity_by_notional = self.max_notional_usd / request.entry_price

        candidates = [
            (quantity_by_risk, "risk_budget"),
            (quantity_by_value, "max_position_pct"),
            (quantity_by_notional, "max_notional"),
        ]
        quantity, binding = min(candidates, key=lambda item: item[0])

        if quantity * request.entry_price < self.min_notional_usd:
            logger.info(
                "sizing_rejected",
                reason="below_min_notional",
                notional=round(quantity * request.entry_price, 2),
                minimum=self.min_notional_usd,
            )
            return None

        unrounded = quantity
        # Round *down*: never assume more size than the budget actually bought.
        from src.backtesting.simulator import round_down

        quantity = round_down(quantity)
        if quantity <= 0:
            return None

        notional = quantity * request.entry_price
        actual_risk = quantity * stop_distance
        risk_pct = actual_risk / request.equity_usd * 100

        logger.info(
            "position_sized",
            notional=round(notional, 2),
            quantity=round(quantity, 8),
            risk_usd=round(actual_risk, 2),
            risk_pct=round(risk_pct, 4),
            capped_by=binding,
        )
        return PositionSizeResult(
            quantity=quantity,
            notional_usd=notional,
            risk_usd=actual_risk,
            risk_pct=risk_pct,
            stop_distance_pct=stop_distance_pct,
            capped_by=binding,
            unrounded_quantity=unrounded,
        )

    def can_afford(self, *, cash_available: float, entry_price: float, quantity: float) -> bool:
        """Cash sufficiency check including an estimated fee buffer."""
        from src.core.config import get_settings

        settings = get_settings()
        notional = quantity * entry_price
        fee_buffer = notional * settings.fee_bps / 10_000
        return notional + fee_buffer <= cash_available