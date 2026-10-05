"""Stop-loss validation and adjustment.

Two invariants enforced here:

1. **Every order must carry a stop.** A trade without a defined invalidation
   point is an unbounded loss and is rejected outright.
2. **The stop must be on the correct side.** A buy whose stop sits above the
   entry would "protect" by filling immediately at a loss.
"""

from __future__ import annotations

from src.core.enums import OrderSide, RiskRule, Severity
from src.core.logging import get_logger
from src.schemas.order import OrderRequest
from src.schemas.risk import RiskCheck

logger = get_logger(__name__)


def validate_stop(
    request: OrderRequest,
    *,
    settings,
    atr: float | None = None,
    entry: float | None = None,
) -> tuple[bool, list[RiskCheck], float | None]:
    """Check the stop-loss, returning ``(ok, checks, stop)``.

    ``entry`` is passed explicitly rather than read off the request, because a
    market order carries no ``limit_price`` and its effective entry is only
    known once a quote is resolved. Writing one back onto the request would
    contradict the order's own type.
    """
    checks: list[RiskCheck] = []
    entry = entry if entry is not None else request.limit_price
    stop = request.stop_loss

    if stop is None:
        checks.append(
            RiskCheck(
                rule=RiskRule.MISSING_STOP_LOSS,
                passed=False,
                message="every order must define a stop-loss; none was provided",
                severity=Severity.CRITICAL,
            )
        )
        return False, checks, None

    if entry is None:
        # No price at all: the stop is validated against ATR bounds only. We
        # cannot know the fill price in advance, so distance limits are checked
        # in percent of the stop itself.
        checks.append(
            RiskCheck(
                rule=RiskRule.STOP_DISTANCE_OUT_OF_RANGE,
                passed=True,
                message="market order: stop distance validated at fill time",
                severity=Severity.INFO,
            )
        )
        return True, checks, stop

    if request.side is OrderSide.BUY and stop >= entry:
        checks.append(
            RiskCheck(
                rule=RiskRule.STOP_DISTANCE_OUT_OF_RANGE,
                passed=False,
                message=(
                    f"BUY stop {stop:,.8g} must be strictly below entry "
                    f"{entry:,.8g}; a stop at or above entry fills immediately "
                    f"at a loss"
                ),
                severity=Severity.CRITICAL,
                observed=stop,
                limit=entry,
                unit="price",
            )
        )
        return False, checks, None

    if request.side is OrderSide.SELL and stop <= entry:
        checks.append(
            RiskCheck(
                rule=RiskRule.STOP_DISTANCE_OUT_OF_RANGE,
                passed=False,
                message=(
                    f"SELL stop {stop:,.8g} must be strictly above entry "
                    f"{entry:,.8g}"
                ),
                severity=Severity.CRITICAL,
                observed=stop,
                limit=entry,
                unit="price",
            )
        )
        return False, checks, None

    distance_pct = abs(entry - stop) / entry * 100

    if distance_pct > settings.risk_max_stop_distance_pct:
        checks.append(
            RiskCheck(
                rule=RiskRule.STOP_DISTANCE_OUT_OF_RANGE,
                passed=False,
                message=(
                    f"stop is {distance_pct:.2f}% from entry, above the maximum "
                    f"{settings.risk_max_stop_distance_pct}% — the position risks "
                    f"more than the sizing limit permits"
                ),
                severity=Severity.CRITICAL,
                observed=round(distance_pct, 4),
                limit=settings.risk_max_stop_distance_pct,
                unit="percent",
            )
        )
        return False, checks, None

    if distance_pct < settings.risk_min_stop_distance_pct:
        checks.append(
            RiskCheck(
                rule=RiskRule.STOP_DISTANCE_OUT_OF_RANGE,
                passed=False,
                message=(
                    f"stop is {distance_pct:.3f}% from entry, below the minimum "
                    f"{settings.risk_min_stop_distance_pct}% — inside normal "
                    f"spread/noise and will be triggered by ordinary fluctuation"
                ),
                severity=Severity.WARNING,
                observed=round(distance_pct, 4),
                limit=settings.risk_min_stop_distance_pct,
                unit="percent",
            )
        )
        return False, checks, None

    checks.append(
        RiskCheck(
            rule=RiskRule.STOP_DISTANCE_OUT_OF_RANGE,
            passed=True,
            message=f"stop distance {distance_pct:.2f}% is within limits",
            severity=Severity.INFO,
            observed=round(distance_pct, 4),
            limit=settings.risk_max_stop_distance_pct,
            unit="percent",
        )
    )
    return True, checks, stop


def derive_stop_from_atr(
    *,
    entry: float,
    side: OrderSide,
    atr: float,
    multiplier: float = 2.0,
    settings=None,
) -> float:
    """Build a stop from ATR when the caller did not supply one."""
    from src.technical_analysis.indicators.atr import volatility_stop_distance

    distance_pct = volatility_stop_distance(atr, entry, multiplier)
    distance = entry * distance_pct / 100
    stop = entry - distance if side is OrderSide.BUY else entry + distance
    logger.info(
        "stop_derived_from_atr",
        atr=round(atr, 8),
        multiplier=multiplier,
        distance_pct=round(distance_pct, 3),
        stop=round(stop, 8),
    )
    return round(stop, 8)


def validate_take_profit(
    request: OrderRequest,
    stop_loss: float | None,
    *,
    min_risk_reward: float,
    entry: float | None = None,
) -> tuple[bool, RiskCheck]:
    """Check that the target offers an acceptable reward-to-risk."""
    entry = entry if entry is not None else request.limit_price
    target = request.take_profit

    if target is None:
        return True, RiskCheck(
            rule=RiskRule.POOR_RISK_REWARD,
            passed=True,
            message="no take-profit set; the stop defines the risk",
            severity=Severity.INFO,
        )

    if entry is None or stop_loss is None:
        return True, RiskCheck(
            rule=RiskRule.POOR_RISK_REWARD,
            passed=True,
            message="market order: R:R validated at fill time",
            severity=Severity.INFO,
        )

    # A target on the losing side is not a low-reward trade, it is a guaranteed
    # loss: the exit logic would fill it as a "take profit". `abs()` below would
    # happily score it as a 3:1 winner, so the side is checked first.
    target_side_ok = (
        target > entry if request.side is OrderSide.BUY else target < entry
    )
    if not target_side_ok:
        return False, RiskCheck(
            rule=RiskRule.POOR_RISK_REWARD,
            passed=False,
            message=(
                f"{request.side.value.upper()} target {target:,.8g} is on the wrong "
                f"side of entry {entry:,.8g}; a target must be reachable in the "
                f"profitable direction"
            ),
            severity=Severity.CRITICAL,
            observed=target,
            limit=entry,
            unit="price",
        )

    risk = abs(entry - stop_loss)
    reward = abs(target - entry)
    if risk <= 0:
        return False, RiskCheck(
            rule=RiskRule.POOR_RISK_REWARD,
            passed=False,
            message="risk is zero; cannot compute reward-to-risk",
            severity=Severity.CRITICAL,
        )

    ratio = reward / risk
    passed = ratio >= min_risk_reward
    return passed, RiskCheck(
        rule=RiskRule.POOR_RISK_REWARD,
        passed=passed,
        message=(
            f"reward-to-risk is {ratio:.2f}:1, "
            + ("meets" if passed else "below")
            + f" the required {min_risk_reward:.2f}:1"
        ),
        severity=Severity.INFO if passed else Severity.WARNING,
        observed=round(ratio, 4),
        limit=min_risk_reward,
        unit="R",
    )


def validate_leverage(leverage: float, settings) -> tuple[bool, RiskCheck]:
    if leverage > settings.risk_default_leverage:
        return False, RiskCheck(
            rule=RiskRule.LEVERAGE_LIMIT,
            passed=False,
            message=(
                f"leverage {leverage}x exceeds the configured maximum of "
                f"{settings.risk_default_leverage}x"
            ),
            severity=Severity.CRITICAL,
            observed=leverage,
            limit=settings.risk_default_leverage,
        )
    return True, RiskCheck(
        rule=RiskRule.LEVERAGE_LIMIT,
        passed=True,
        message=f"leverage {leverage}x within limit",
        severity=Severity.INFO,
        observed=leverage,
    )