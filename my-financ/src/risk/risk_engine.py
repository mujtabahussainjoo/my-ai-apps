"""The hard risk engine.

This is the only component allowed to say an order may execute. The layering
that Framework.md insists on is enforced structurally, not by convention:

    src/strategies  ->  "BUY candidate"     (no portfolio access)
    src/agents      ->  "analysis says BUY" (no execution access)
    src/risk        ->  "ALLOWED / REJECTED"
    src/trading     ->  executes only on RiskAssessment.allowed

Design rules for this module:

- **Fail closed.** An exception during assessment must produce a rejection, not
  an approval. Every check is therefore wrapped so a bug cannot become an
  "allow".
- **Every rejection names a rule** and carries observed/limit numbers, so an
  operator can see which limit bound and by how much.
- **The engine never widens risk.** It may *reduce* a position (returning
  ``APPROVED_REDUCED``) but never increase one.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.core.config import Settings, get_settings
from src.core.constants import MAX_AI_TRADES_PER_DAY, MAX_QUOTE_AGE_SECONDS
from src.core.enums import (
    OrderSide,
    RiskLevel,
    RiskRule,
    RiskVerdict,
    Severity,
    SignalAction,
    StrategyStatus,
    TradingMode,
)
from src.core.logging import get_logger
from src.core.security import assert_live_trading_allowed, kill_switch
from src.risk.exposure import ExposureTracker
from src.risk.position_sizing import PositionSizer
from src.risk.risk_limits import (
    LimitBreakers,
    validate_daily_loss,
    validate_daily_trade_count,
    validate_drawdown,
)
from src.risk.stop_loss import (
    derive_stop_from_atr,
    validate_leverage,
    validate_stop,
    validate_take_profit,
)
from src.schemas.market import Ticker
from src.schemas.order import OrderRequest
from src.schemas.portfolio import PortfolioSnapshot, Position
from src.schemas.risk import RiskAssessment, RiskCheck, RiskEvent
from src.schemas.signal import Signal, TradeProposal

logger = get_logger(__name__)

#: Limits whose breach can be relieved by trading *less*. Nothing else may be
#: reduced: a smaller order does not make a stale quote fresh, does not qualify
#: a strategy, and does not unlock a mode the operator has not enabled.
_REDUCIBLE_RULES = frozenset(
    {
        RiskRule.MAX_TOTAL_EXPOSURE,
        RiskRule.EXISTING_SYMBOL_EXPOSURE,
        RiskRule.MAX_POSITION_SIZE,
    }
)


class RiskEngine:
    """Stateless assessment, plus the breaker state it owns."""

    def __init__(
        self,
        settings: Settings | None = None,
        breakers: LimitBreakers | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.breakers = breakers or LimitBreakers()
        self.sizer = PositionSizer(
            max_position_pct=self.settings.risk_max_position_pct,
            max_risk_per_trade_pct=self.settings.risk_max_risk_per_trade_pct,
        )
        self.exposure = ExposureTracker(
            max_total_exposure_pct=self.settings.risk_max_total_exposure_pct,
            max_open_positions=self.settings.risk_max_open_positions,
        )

    # ── Public API ──────────────────────────────────────────────────────────
    def assess(
        self,
        request: OrderRequest,
        portfolio: PortfolioSnapshot,
        *,
        ticker: Ticker | None = None,
        positions: list[Position] | None = None,
        signal: Signal | None = None,
        proposal: TradeProposal | None = None,
        agent_approved: bool = True,
        # CANDIDATE, never QUALIFIED: a caller who forgets to pass the stored
        # status must fail closed, not inherit permission to trade.
        strategy_status: StrategyStatus = StrategyStatus.CANDIDATE,
        atr: float | None = None,
        correlations: dict[str, float] | None = None,
    ) -> RiskAssessment:
        """Assess one order. Returns a verdict; never raises for a rejection."""
        checks: list[RiskCheck] = []
        positions = list(positions if positions is not None else portfolio.positions)
        request = request.model_copy(deep=True)

        try:
            checks.extend(self._check_circuit_breakers(portfolio))
            if any(c.rule == RiskRule.KILL_SWITCH and not c.passed for c in checks):
                return self._verdict(
                    RiskVerdict.HALTED, checks, portfolio, reason="kill switch engaged"
                )

            if any(not c.passed for c in checks):
                return self._verdict(RiskVerdict.REJECTED, checks, portfolio)

            checks.extend(self._check_mode(request))
            checks.extend(self._check_data_freshness(ticker))
            checks.extend(self._check_strategy(request, strategy_status))
            checks.extend(self._check_agent(signal, proposal, agent_approved))
            checks.extend(self._check_structure(request))
            checks.extend(self._check_leverage(request))

            # Size-dependent limits cannot be evaluated until we know the
            # entry price and quantity, but the non-reducible ones must be
            # settled first: shrinking a trade never rescues a bad mode, a
            # stale quote, or an unqualified strategy.
            blocking = [
                c for c in checks if not c.passed and c.rule not in _REDUCIBLE_RULES
            ]
            if blocking:
                return self._verdict(RiskVerdict.REJECTED, checks, portfolio)

            entry_price = self._entry_price(request, ticker)
            if entry_price is None:
                checks.append(
                    RiskCheck(
                        rule=RiskRule.INVALID_ORDER,
                        passed=False,
                        message="cannot determine an entry price: no limit price and no ticker",
                        severity=Severity.CRITICAL,
                    )
                )
                return self._verdict(RiskVerdict.REJECTED, checks, portfolio)
            # Derive protection before validating it: a caller-supplied stop is
            # never re-validated on its way in, so the fallback has to exist.
            if request.stop_loss is None and atr and entry_price:
                request.stop_loss = derive_stop_from_atr(
                    entry=entry_price, side=request.side, atr=atr, settings=self.settings
                )
                logger.warning(
                    "stop_derived_by_engine",
                    symbol=request.symbol,
                    stop=request.stop_loss,
                    atr=round(atr, 8),
                    note="caller supplied no stop-loss; ATR-derived protection applied",
                )

            stop_ok, stop_checks, _ = validate_stop(
                request, settings=self.settings, atr=atr, entry=entry_price
            )
            checks.extend(stop_checks)
            if not stop_ok:
                return self._verdict(RiskVerdict.REJECTED, checks, portfolio)

            rr_ok, rr_check = validate_take_profit(
                request,
                request.stop_loss,
                min_risk_reward=self.settings.qualify_min_risk_reward,
                entry=entry_price,
            )
            checks.append(rr_check)
            if not rr_ok:
                return self._verdict(RiskVerdict.REJECTED, checks, portfolio)

            requested_notional = self._requested_notional(request, entry_price)
            sizing = self._size(request, entry_price, portfolio)
            if sizing is None:
                checks.append(
                    RiskCheck(
                        rule=RiskRule.MAX_POSITION_SIZE,
                        passed=False,
                        message="position sizing produced no tradeable quantity",
                        severity=Severity.WARNING,
                    )
                )
                return self._verdict(RiskVerdict.REJECTED, checks, portfolio)

            quantity, notional, risk_usd = sizing
            capped_by_engine = notional < requested_notional

            checks.append(self._exposure_check(request.symbol, notional, positions, portfolio, correlations))
            checks.append(self._risk_per_trade_check(risk_usd, portfolio))
            checks.append(self._balance_check(notional, portfolio))
            checks.append(self._min_notional_check(notional))

            verdict = RiskVerdict.APPROVED
            if capped_by_engine:
                verdict = RiskVerdict.APPROVED_REDUCED

            failed = [c for c in checks if not c.passed]
            if failed:
                reduced = self._attempt_reduction(
                    request, entry_price, portfolio, failed, positions
                )
                if reduced is None:
                    return self._verdict(RiskVerdict.REJECTED, checks, portfolio)
                quantity, notional, risk_usd = reduced
                verdict = RiskVerdict.APPROVED_REDUCED

            risk_usd_pct = (risk_usd / portfolio.equity_usd * 100) if portfolio.equity_usd else 0.0
            risk_level = self._classify_risk(risk_usd_pct, portfolio, notional)

            self.breakers.record_trade()
            assessment = RiskAssessment(
                verdict=verdict,
                approved_quantity=quantity,
                approved_notional_usd=notional,
                approved_risk_usd=risk_usd,
                checks=checks,
                risk_level=risk_level,
                adjusted_stop_loss=request.stop_loss,
                adjusted_take_profit=request.take_profit,
                leverage=request.leverage,
                requires_approval=self._requires_approval(request.mode),
            )
            logger.info(
                "risk_approved",
                symbol=request.symbol,
                verdict=verdict.value,
                notional=round(notional, 2),
                quantity=round(quantity, 8),
                risk_usd=round(risk_usd, 2),
                risk_level=risk_level.value,
                mode=TradingMode(request.mode).value,
            )
            return assessment

        except Exception as exc:  # noqa: BLE001 - fail closed, always
            logger.error("risk_engine_error", error=str(exc), error_type=type(exc).__name__)
            checks.append(
                RiskCheck(
                    rule=RiskRule.INVALID_ORDER,
                    passed=False,
                    message=(
                        f"risk assessment failed unexpectedly ({type(exc).__name__}); "
                        f"order rejected as a precaution"
                    ),
                    severity=Severity.CRITICAL,
                )
            )
            return self._verdict(RiskVerdict.REJECTED, checks, portfolio)

    def assess_exit(
        self,
        request: OrderRequest,
        portfolio: PortfolioSnapshot,
        *,
        ticker: Ticker | None = None,
        reason: str | None = None,
    ) -> RiskAssessment:
        """Assess a risk-reducing order against the exit-side controls only.

        A stop must never be blocked by the very limits that created the
        position, or the portfolio ends up trapped: exposure caps and
        qualification gates are *admission* controls, so they are skipped here.
        That exemption is narrow and deliberate. What still applies:

        - the kill switch and the circuit breakers, because those are
          operator-level halts that mean "do not trade", not "do not open risk";
        - the mode check, so a paper exit can never be smuggled into a live
          session or the reverse;
        - data freshness, because the exit is priced off the ticker and a
          stale quote would fill against a price that no longer exists.

        Everything else - qualification, stop geometry, risk/reward, sizing and
        exposure - is entry-side and does not apply to closing.
        """
        checks: list[RiskCheck] = []
        try:
            checks.extend(self._check_circuit_breakers(portfolio))
            checks.extend(self._check_mode(request))
            checks.extend(self._check_data_freshness(ticker))

            blocking = [c for c in checks if not c.passed]
            if blocking:
                return self._verdict(RiskVerdict.REJECTED, checks, portfolio)

            price = self._entry_price(request, ticker)
            quantity = float(request.quantity or 0.0)
            checks.append(
                RiskCheck(
                    rule=RiskRule.POSITION_REDUCING,
                    passed=True,
                    message=(
                        "risk-reducing exit approved"
                        + (f" ({reason})" if reason else "")
                        + f": {quantity:g} at {price if price else 'market'}"
                    ),
                    severity=Severity.INFO,
                )
            )
        except Exception as exc:  # noqa: BLE001 - fail closed, as assess does
            logger.error("risk_engine_exit_error", error=str(exc), error_type=type(exc).__name__)
            checks.append(
                RiskCheck(
                    rule=RiskRule.INVALID_ORDER,
                    passed=False,
                    message=(
                        f"exit assessment failed unexpectedly ({type(exc).__name__}); "
                        f"order rejected as a precaution"
                    ),
                    severity=Severity.CRITICAL,
                )
            )
            return self._verdict(RiskVerdict.REJECTED, checks, portfolio)

        assessment = self._verdict(RiskVerdict.APPROVED, checks, portfolio)
        return assessment.model_copy(
            update={
                "approved_quantity": quantity,
                "approved_notional_usd": quantity * (price or 0.0),
                "approved_risk_usd": 0.0,
            }
        )

    def assess_proposal(
        self,
        proposal: TradeProposal,
        portfolio: PortfolioSnapshot,
        *,
        ticker: Ticker | None = None,
        positions: list[Position] | None = None,
        # CANDIDATE, never QUALIFIED: a caller who forgets to pass the stored
        # status must fail closed, not inherit permission to trade.
        strategy_status: StrategyStatus = StrategyStatus.CANDIDATE,
        mode: TradingMode = TradingMode.PAPER,
        agent_approved: bool = True,
        atr: float | None = None,
    ) -> RiskAssessment:
        """Convert an agent proposal into a request, then assess it.

        The agent's proposed stop and target are treated as *suggestions*: they
        are overwritten here if they violate limits. The agent cannot choose its
        own risk.
        """
        side = OrderSide.BUY if proposal.action is SignalAction.BUY else OrderSide.SELL
        request = OrderRequest(
            symbol=proposal.symbol,
            side=side,
            order_type="market",
            notional_usd=portfolio.equity_usd * (proposal.position_size_pct / 100),
            stop_loss=proposal.stop_loss,
            take_profit=proposal.take_profit,
            strategy=proposal.strategy,
            mode=mode,
        )
        return self.assess(
            request,
            portfolio,
            ticker=ticker,
            positions=positions,
            proposal=proposal,
            agent_approved=agent_approved,
            strategy_status=strategy_status,
            atr=atr,
        )

    def breaker_status(self, portfolio: PortfolioSnapshot) -> object:
        return self.breakers.status(
            self.settings,
            equity=portfolio.equity_usd,
            daily_pnl=portfolio.daily_pnl_usd,
            drawdown_pct=portfolio.current_drawdown_pct,
        )

    # ── Individual checks ───────────────────────────────────────────────────
    def _check_circuit_breakers(self, portfolio: PortfolioSnapshot) -> list[RiskCheck]:
        checks: list[RiskCheck] = []

        if kill_switch.engaged:
            checks.append(
                RiskCheck(
                    rule=RiskRule.KILL_SWITCH,
                    passed=False,
                    message=f"kill switch engaged: {kill_switch.reason}",
                    severity=Severity.CRITICAL,
                )
            )
            return checks  # Short-circuit: nothing else matters.

        daily_reason = validate_daily_loss(
            settings=self.settings,
            breakers=self.breakers,
            equity_usd=portfolio.equity_usd,
            daily_pnl_usd=portfolio.daily_pnl_usd,
        )
        checks.append(
            RiskCheck(
                rule=RiskRule.DAILY_LOSS_LIMIT,
                passed=daily_reason is None,
                message=daily_reason or "daily loss within limit",
                severity=Severity.CRITICAL,
                observed=round(portfolio.daily_pnl_usd, 2),
                limit=-round(
                    portfolio.equity_usd * self.settings.risk_daily_loss_limit_pct / 100, 2
                ),
                unit="usd",
            )
        )

        drawdown_reason = validate_drawdown(
            settings=self.settings,
            breakers=self.breakers,
            peak_equity_usd=portfolio.peak_equity_usd,
            current_equity_usd=portfolio.equity_usd,
        )
        checks.append(
            RiskCheck(
                rule=RiskRule.MAX_DRAWDOWN,
                passed=drawdown_reason is None,
                message=drawdown_reason or "drawdown within limit",
                severity=Severity.CRITICAL,
                observed=round(portfolio.current_drawdown_pct, 3),
                limit=self.settings.risk_max_drawdown_pct,
                unit="percent",
            )
        )

        budget_reason = validate_daily_trade_count(self.breakers, MAX_AI_TRADES_PER_DAY)
        checks.append(
            RiskCheck(
                rule=RiskRule.MAX_AI_TRADES_PER_DAY,
                passed=budget_reason is None,
                message=budget_reason
                or f"daily trade budget {self.breakers.trades_today}/{MAX_AI_TRADES_PER_DAY}",
                severity=Severity.CRITICAL,
                observed=self.breakers.trades_today,
                limit=MAX_AI_TRADES_PER_DAY,
                unit="trades",
            )
        )
        return checks

    def _check_mode(self, request: OrderRequest) -> list[RiskCheck]:
        checks: list[RiskCheck] = []
        requested = TradingMode(request.mode)
        configured = TradingMode(self.settings.trading_mode)

        if requested.uses_real_money and not self.settings.live_trading_enabled:
            return [
                RiskCheck(
                    rule=RiskRule.MODE_NOT_ALLOWED,
                    passed=False,
                    message=(
                        f"live trading is not enabled (LIVE_TRADING_ENABLED=false); "
                        f"configured mode is {configured.value}"
                    ),
                    severity=Severity.CRITICAL,
                )
            ]

        if requested.rank > configured.rank:
            checks.append(
                RiskCheck(
                    rule=RiskRule.MODE_NOT_ALLOWED,
                    passed=False,
                    message=(
                        f"requested mode {requested.value} is more permissive than the "
                        f"configured mode {configured.value}; escalation must be an "
                        f"explicit operator action"
                    ),
                    severity=Severity.CRITICAL,
                )
            )
        else:
            checks.append(
                RiskCheck(
                    rule=RiskRule.MODE_NOT_ALLOWED,
                    passed=True,
                    message=f"mode {requested.value} permitted by configured {configured.value}",
                    severity=Severity.INFO,
                )
            )
        return checks

    def _check_data_freshness(self, ticker: Ticker | None) -> list[RiskCheck]:
        if ticker is None:
            return [
                RiskCheck(
                    rule=RiskRule.STALE_MARKET_DATA,
                    passed=False,
                    message="no market data supplied; refusing to price an order blind",
                    severity=Severity.CRITICAL,
                )
            ]

        age = (datetime.now(timezone.utc) - ticker.timestamp).total_seconds()
        stale = age > MAX_QUOTE_AGE_SECONDS
        return [
            RiskCheck(
                rule=RiskRule.STALE_MARKET_DATA,
                passed=not stale,
                message=(
                    f"quote is {age:.0f}s old, limit {MAX_QUOTE_AGE_SECONDS}s"
                    if stale
                    else f"quote age {age:.0f}s is fresh"
                ),
                severity=Severity.CRITICAL,
                observed=round(age, 1),
                limit=MAX_QUOTE_AGE_SECONDS,
                unit="seconds",
            )
        ]

    def _check_strategy(
        self, request: OrderRequest, status: StrategyStatus
    ) -> list[RiskCheck]:
        if request.strategy is None:
            return [
                RiskCheck(
                    rule=RiskRule.STRATEGY_NOT_QUALIFIED,
                    passed=False,
                    message=(
                        "no strategy supplied; every trade must be attributable to a "
                        "qualified strategy"
                    ),
                    severity=Severity.CRITICAL,
                )
            ]

        passed = status is StrategyStatus.QUALIFIED
        return [
            RiskCheck(
                rule=RiskRule.STRATEGY_NOT_QUALIFIED,
                passed=passed,
                message=(
                    f"strategy '{request.strategy}' status is {status.value}"
                    + ("" if passed else "; it has not passed the qualification gate")
                ),
                severity=Severity.CRITICAL if not passed else Severity.INFO,
            )
        ]

    def _check_agent(
        self,
        signal: Signal | None,
        proposal: TradeProposal | None,
        agent_approved: bool,
    ) -> list[RiskCheck]:
        checks: list[RiskCheck] = []

        if not agent_approved:
            checks.append(
                RiskCheck(
                    rule=RiskRule.AGENT_NOT_APPROVED,
                    passed=False,
                    message="the agent layer did not approve this trade",
                    severity=Severity.WARNING,
                )
            )

        if signal is not None and not signal.is_actionable:
            checks.append(
                RiskCheck(
                    rule=RiskRule.AGENT_OUTPUT_INVALID,
                    passed=False,
                    message=(
                        f"signal is not actionable: action={signal.action.value}, "
                        f"risk-reward="
                        f"{signal.risk_reward:.2f}"
                        if signal.risk_reward
                        else "signal is not actionable"
                    ),
                    severity=Severity.WARNING,
                )
            )

        if proposal is not None:
            if proposal.action is SignalAction.HOLD:
                checks.append(
                    RiskCheck(
                        rule=RiskRule.AGENT_OUTPUT_INVALID,
                        passed=False,
                        message="proposal action is HOLD, which is not a trade",
                        severity=Severity.WARNING,
                    )
                )
            # The agent's stop is advisory; confirm it is not a wildcard.
            risk = abs(proposal.entry - proposal.stop_loss)
            if risk <= 0:
                checks.append(
                    RiskCheck(
                        rule=RiskRule.AGENT_OUTPUT_INVALID,
                        passed=False,
                        message="proposal stop_loss equals entry (zero risk definition)",
                        severity=Severity.CRITICAL,
                    )
                )

        if not checks:
            checks.append(
                RiskCheck(
                    rule=RiskRule.AGENT_NOT_APPROVED,
                    passed=True,
                    message="agent approved the trade",
                    severity=Severity.INFO,
                )
            )
        return checks

    def _check_structure(self, request: OrderRequest) -> list[RiskCheck]:
        problems: list[str] = []

        if request.notional_usd is not None and request.notional_usd <= 0:
            problems.append("notional_usd must be positive")
        if request.quantity is not None and request.quantity <= 0:
            problems.append("quantity must be positive")
        if (request.quantity is None) == (request.notional_usd is None):
            problems.append("exactly one of quantity or notional_usd is required")

        return [
            RiskCheck(
                rule=RiskRule.INVALID_ORDER,
                passed=not problems,
                message="; ".join(problems) or "order structure valid",
                severity=Severity.CRITICAL if problems else Severity.INFO,
            )
        ]

    def _check_leverage(self, request: OrderRequest) -> list[RiskCheck]:
        return [validate_leverage(request.leverage, self.settings)[1]]

    def _exposure_check(
        self,
        symbol: str,
        notional: float,
        positions: list[Position],
        portfolio: PortfolioSnapshot,
        correlations: dict[str, float] | None,
    ) -> RiskCheck:
        ok, message = self.exposure.check(
            symbol=symbol,
            additional_notional_usd=notional,
            positions=positions,
            equity_usd=portfolio.equity_usd,
            correlations=correlations,
        )
        observed = self.exposure.compute(
            positions, portfolio.equity_usd, correlations
        ).exposure_pct
        return RiskCheck(
            rule=RiskRule.MAX_TOTAL_EXPOSURE,
            passed=ok,
            message=message or "exposure within limits",
            severity=Severity.WARNING if not ok else Severity.INFO,
            observed=round(observed, 3),
            limit=self.settings.risk_max_total_exposure_pct,
            unit="percent of equity",
        )

    def _risk_per_trade_check(self, risk_usd: float, portfolio: PortfolioSnapshot) -> RiskCheck:
        limit_usd = portfolio.equity_usd * self.settings.risk_max_risk_per_trade_pct / 100
        return RiskCheck(
            rule=RiskRule.MAX_RISK_PER_TRADE,
            passed=risk_usd <= limit_usd + 1e-9,
            message=(
                f"risk ${risk_usd:,.2f} vs limit ${limit_usd:,.2f} "
                f"({self.settings.risk_max_risk_per_trade_pct}% of equity)"
            ),
            severity=Severity.CRITICAL if risk_usd > limit_usd else Severity.INFO,
            observed=round(risk_usd, 2),
            limit=round(limit_usd, 2),
            unit="usd",
        )

    def _balance_check(self, notional: float, portfolio: PortfolioSnapshot) -> RiskCheck:
        fee_buffer = notional * self.settings.fee_bps / 10_000
        needed = notional + fee_buffer
        ok = needed <= portfolio.cash_usd
        return RiskCheck(
            rule=RiskRule.INSUFFICIENT_BALANCE,
            passed=ok,
            message=(
                f"cash ${portfolio.cash_usd:,.2f} vs required ${needed:,.2f} "
                f"(incl. fee buffer)"
            ),
            severity=Severity.CRITICAL if not ok else Severity.INFO,
            observed=round(portfolio.cash_usd, 2),
            limit=round(needed, 2),
            unit="usd",
        )

    def _min_notional_check(self, notional: float) -> RiskCheck:
        from src.core.constants import MIN_ORDER_NOTIONAL_USD

        ok = notional >= MIN_ORDER_NOTIONAL_USD
        return RiskCheck(
            rule=RiskRule.MIN_ORDER_NOTIONAL,
            passed=ok,
            message=(
                f"notional ${notional:,.2f} below minimum ${MIN_ORDER_NOTIONAL_USD}"
                if not ok
                else f"notional ${notional:,.2f} acceptable"
            ),
            severity=Severity.WARNING,
            observed=round(notional, 2),
            limit=MIN_ORDER_NOTIONAL_USD,
            unit="usd",
        )

    # ── Sizing ──────────────────────────────────────────────────────────────
    def _entry_price(self, request: OrderRequest, ticker: Ticker | None) -> float | None:
        if request.limit_price is not None:
            return request.limit_price
        if ticker is None:
            return None
        # Buy at the ask, sell at the bid: never assume the mid fills.
        return ticker.ask if (request.side is OrderSide.BUY and ticker.ask) else (
            ticker.bid if (request.side is OrderSide.SELL and ticker.bid) else ticker.last
        )

    def _size(
        self, request: OrderRequest, entry_price: float, portfolio: PortfolioSnapshot
    ) -> tuple[float, float, float] | None:
        """Return ``(quantity, notional, risk_usd)`` or ``None``."""
        if request.quantity is not None:
            quantity = float(request.quantity)
            notional = quantity * entry_price
        else:
            notional = float(request.notional_usd or 0.0)
            quantity = notional / entry_price if entry_price > 0 else 0.0

        # Apply the portfolio caps to an explicitly requested quantity too.
        max_notional = portfolio.equity_usd * self.settings.risk_max_position_pct / 100
        if notional > max_notional:
            logger.warning(
                "requested_quantity_capped",
                requested=round(notional, 2),
                maximum=round(max_notional, 2),
            )
            notional = max_notional
            quantity = notional / entry_price

        if quantity <= 0 or notional <= 0:
            return None

        if request.stop_loss is not None:
            risk_usd = abs(entry_price - request.stop_loss) * quantity
        else:
            risk_usd = notional * self.settings.risk_max_risk_per_trade_pct / 100
        return quantity, notional, risk_usd

    def _attempt_reduction(
        self,
        request: OrderRequest,
        entry_price: float,
        portfolio: PortfolioSnapshot,
        failed: list[RiskCheck],
        positions: list[Position],
    ) -> tuple[float, float, float] | None:
        """Shrink the order to fit the remaining exposure headroom.

        Returns ``None`` when no reduction can satisfy the failed checks. Only
        size is ever reduced — never the stop, never the risk budget.
        """
        # Only size-dependent limits may be relieved by shrinking. Anything
        # else (mode, staleness, strategy status, R:R, trade budget) is fatal.
        if any(check.rule not in _REDUCIBLE_RULES for check in failed):
            logger.warning(
                "reduction_declined",
                symbol=request.symbol,
                fatal_rules=[c.rule for c in failed if c.rule not in _REDUCIBLE_RULES],
            )
            return None

        headroom = self.exposure.remaining_capacity_usd(portfolio.equity_usd, positions)
        max_position_notional = (
            portfolio.equity_usd * self.settings.risk_max_position_pct / 100
        )
        target_notional = min(headroom, max_position_notional)

        if request.notional_usd is not None:
            target_notional = min(target_notional, request.notional_usd)

        if target_notional <= 0:
            return None

        quantity = target_notional / entry_price
        if request.quantity is not None:
            quantity = min(quantity, request.quantity)

        risk_usd = (
            abs(entry_price - request.stop_loss) * quantity
            if request.stop_loss is not None
            else target_notional * self.settings.risk_max_risk_per_trade_pct / 100
        )

        # The reduced size must still satisfy the hard per-trade risk limit.
        max_risk = portfolio.equity_usd * self.settings.risk_max_risk_per_trade_pct / 100
        if risk_usd > max_risk + 1e-9:
            return None

        from src.core.constants import MIN_ORDER_NOTIONAL_USD

        if quantity * entry_price < MIN_ORDER_NOTIONAL_USD:
            return None

        from src.backtesting.simulator import round_down

        quantity = round_down(quantity)
        if quantity <= 0:
            return None

        notional = quantity * entry_price
        risk_usd = (
            abs(entry_price - request.stop_loss) * quantity
            if request.stop_loss is not None
            else notional * self.settings.risk_max_risk_per_trade_pct / 100
        )

        logger.info(
            "risk_reduced_size",
            symbol=request.symbol,
            new_notional=round(notional, 2),
            new_quantity=round(quantity, 8),
            reason="exposure limit; order reduced rather than rejected",
        )
        # The limit is genuinely satisfied now, so record that, and why the
        # order is smaller than requested.
        for check in failed:
            check.message = f"{check.message} — order reduced to fit available headroom"
            check.passed = True
        return quantity, notional, risk_usd

    # ── Helpers ─────────────────────────────────────────────────────────────
    def _requested_notional(self, request: OrderRequest, entry_price: float) -> float:
        if request.notional_usd is not None:
            return float(request.notional_usd)
        if request.quantity is not None:
            return float(request.quantity) * entry_price
        return 0.0

    def _requires_approval(self, mode: TradingMode) -> bool:
        return mode.uses_real_money

    def _classify_risk(
        self, risk_pct: float, portfolio: PortfolioSnapshot, notional: float
    ) -> RiskLevel:
        score = risk_pct
        if portfolio.current_drawdown_pct > self.settings.risk_max_drawdown_pct * 0.6:
            score *= 1.5
        if portfolio.exposure_pct > self.settings.risk_max_total_exposure_pct * 0.8:
            score *= 1.3
        if score >= self.settings.risk_max_risk_per_trade_pct:
            return RiskLevel.EXTREME
        if score >= self.settings.risk_max_risk_per_trade_pct * 0.75:
            return RiskLevel.HIGH
        if score >= self.settings.risk_max_risk_per_trade_pct * 0.4:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _verdict(
        self,
        verdict: RiskVerdict,
        checks: list[RiskCheck],
        portfolio: PortfolioSnapshot,
        reason: str | None = None,
    ) -> RiskAssessment:
        failed = [c for c in checks if not c.passed]
        if reason:
            logger.warning("risk_halted", reason=reason)
        if failed:
            logger.warning(
                "risk_rejected",
                verdict=verdict.value,
                rules=[c.rule for c in failed],
                reasons=[c.message for c in failed],
                equity=round(portfolio.equity_usd, 2),
            )
        return RiskAssessment(
            verdict=verdict,
            approved_quantity=0.0,
            approved_notional_usd=0.0,
            approved_risk_usd=0.0,
            checks=checks,
            risk_level=RiskLevel.HIGH if failed else RiskLevel.LOW,
        )

    def engage_kill_switch(self, reason: str) -> None:
        kill_switch.engage(reason)

    def release_kill_switch(self, *, operator: str) -> None:
        kill_switch.release(operator=operator)


_engine: RiskEngine | None = None


def get_risk_engine(settings: Settings | None = None) -> RiskEngine:
    """Shared engine instance so breaker state survives across requests."""
    global _engine
    if _engine is None or settings is not None:
        _engine = RiskEngine(settings)
    return _engine


def reset_risk_engine() -> None:
    """Test helper: drop the shared engine and its breaker state."""
    global _engine
    _engine = None
    kill_switch.release(operator="test_reset")


def build_risk_event(
    assessment: RiskAssessment, symbol: str, rule: str | None = None
) -> list[RiskEvent]:
    """Convert failed checks into persistable risk events."""
    from uuid import uuid4

    return [
        RiskEvent(
            id=uuid4().hex[:16],
            rule=check.rule,
            severity=check.severity,
            symbol=symbol,
            message=check.message,
            passed=check.passed,
            observed=check.observed,
            limit=check.limit,
        )
        for check in assessment.checks
        if not check.passed and (rule is None or check.rule == rule)
    ]


def assert_no_live_execution(mode: TradingMode, settings: Settings | None = None) -> None:
    """Module-level guard for any code path that reaches an exchange."""
    settings = settings or get_settings()
    assert_live_trading_allowed(
        mode,
        live_enabled=settings.live_trading_enabled,
        acknowledgement=settings.live_trading_i_understand_the_risk,
    )

