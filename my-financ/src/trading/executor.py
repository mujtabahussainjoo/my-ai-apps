"""Order execution: the only path from an approved assessment to a fill.

The invariant this module exists to enforce:

    No order reaches a venue without an allowed :class:`RiskAssessment`, and the
    quantity that reaches the venue is the risk engine's number, never the
    caller's.

Everything else — the broker choice, the ledger writes, the audit trail — is
secondary to keeping that true.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from src.core.config import get_settings
from src.core.enums import TradingMode
from src.core.logging import get_logger
from src.core.security import idempotency_key
from src.database.base import new_id
from src.database.repositories import (
    ApprovalRepository,
    OrderRepository,
    PortfolioRepository,
    RiskRepository,
    SystemEventRepository,
    TradeRepository,
)
from src.risk.risk_engine import RiskEngine
from src.schemas.market import Ticker
from src.schemas.order import Order, OrderRequest
from src.schemas.portfolio import PortfolioSnapshot
from src.schemas.risk import RiskAssessment, RiskVerdict
from src.trading.base import Broker, ExecutionInstruction, FillReport, side_value
from src.trading.paper.broker import PaperBroker

logger = get_logger(__name__)


class ExecutionRejected(Exception):
    """The risk gate refused this order. Nothing was sent to any venue."""

    def __init__(self, assessment: RiskAssessment, message: str | None = None) -> None:
        self.assessment = assessment
        reason = message or "; ".join(assessment.reasons) or "rejected by risk engine"
        super().__init__(reason)


class ExecutionOutcome:
    """What happened to one submission attempt."""

    def __init__(
        self,
        *,
        status: str,
        detail: str,
        order_id: str | None = None,
        fill: FillReport | None = None,
        assessment_id: str | None = None,
    ) -> None:
        self.status = status
        self.detail = detail
        self.order_id = order_id
        self.fill = fill
        self.assessment_id = assessment_id

    @property
    def executed(self) -> bool:
        return self.status in ("filled", "partially_filled", "open")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"ExecutionOutcome(status={self.status!r}, order_id={self.order_id!r})"


@dataclass(slots=True)
class ExecutorConfig:
    mode: TradingMode = TradingMode.PAPER
    require_approval_when_flagged: bool = True
    allowed_modes: tuple[TradingMode, ...] = field(
        default_factory=lambda: (TradingMode.PAPER, TradingMode.TESTNET, TradingMode.LIVE)
    )


class OrderExecutor:
    """Routes authorised orders to a venue and records the outcome."""

    def __init__(
        self,
        session: Session,
        broker: Broker,
        *,
        config: ExecutorConfig | None = None,
        risk_engine: RiskEngine | None = None,
    ) -> None:
        self.session = session
        self.broker = broker
        self.config = config or ExecutorConfig(mode=broker.mode)
        #: Only exits consult the engine directly; entries arrive pre-assessed.
        #: The mode is pinned to the executor's so a testnet or live executor is
        #: not judged against the process-wide paper default.
        self.risk_engine = risk_engine or RiskEngine(
            get_settings().model_copy(update={"trading_mode": self.config.mode.value})
        )
        self.orders = OrderRepository(session)
        self.trades = TradeRepository(session)
        self.portfolio = PortfolioRepository(session)
        self.risk = RiskRepository(session)
        self.approvals = ApprovalRepository(session)
        self.events = SystemEventRepository(session)
        #: Set by close_position so the realised trade keeps its true reason.
        self._exit_reason: str | None = None

    # ── The gate ─────────────────────────────────────────────────────────────
    def execute(
        self,
        request: OrderRequest,
        assessment: RiskAssessment,
        *,
        ticker: Ticker,
        portfolio: PortfolioSnapshot | None = None,
        approval_id: str | None = None,
    ) -> ExecutionOutcome:
        """Execute an order that the risk engine has already approved.

        Raises :class:`ExecutionRejected` if the assessment does not allow
        trading. Every rejection is written to the audit trail before returning.
        """
        if request.mode is not self.config.mode:
            raise ExecutionRejected(
                assessment,
                f"request mode {request.mode.value!r} does not match executor mode "
                f"{self.config.mode.value!r}",
            )

        if not assessment.allowed:
            self._audit_rejection(request, assessment, portfolio)
            raise ExecutionRejected(assessment, describe_rejection(assessment))

        if assessment.verdict is RiskVerdict.APPROVED_REDUCED and assessment.approved_quantity <= 0:
            self._audit_rejection(request, assessment, portfolio)
            raise ExecutionRejected(assessment, "reduced verdict left no executable quantity")

        if (
            assessment.requires_approval
            and self.config.require_approval_when_flagged
            and self.config.mode is TradingMode.LIVE
            and approval_id is None
        ):
            raise ExecutionRejected(assessment, "live execution requires a human approval id")

        if approval_id is not None and not self._approval_is_valid(request, approval_id):
            raise ExecutionRejected(assessment, f"approval {approval_id!r} is not valid for this order")

        # From here on the numbers are the risk engine's, not the caller's.
        try:
            instruction = self._build_instruction(request, assessment)
        except ExecutionRejected:
            self._audit_rejection(request, assessment, portfolio)
            raise

        fill = self.broker.submit(instruction, ticker)
        order = self._persist(request, assessment, instruction, fill)
        # An approval that is never written down is indistinguishable from one
        # that never happened, so the decision is filed against the order it
        # authorised and the outcome reports the real row id.
        assessment_row = self._record_assessment(
            request, assessment, portfolio, order_id=order.id
        )
        self._write_snapshot(portfolio)
        self.session.commit()

        return ExecutionOutcome(
            status=fill.status,
            detail=(
                f"{fill.filled_quantity:g}/{instruction.quantity:g} {request.symbol} "
                f"at {fill.average_price or 'n/a'}"
            ),
            order_id=order.id,
            fill=fill,
            assessment_id=assessment_row.id,
        )

    # ── Instruction construction ─────────────────────────────────────────────
    def _build_instruction(
        self, request: OrderRequest, assessment: RiskAssessment
    ) -> ExecutionInstruction:
        """Derive the authorised instruction, ignoring caller-supplied sizing.

        The quantity comes from the assessment and nowhere else. It is tempting
        to fall back to ``request.quantity`` when the assessment carries no size,
        but that would hand the caller back the authority the risk engine just
        withheld — so an unsized approval is rejected instead.
        """
        quantity = assessment.approved_quantity
        if quantity <= 0:
            # Some paths authorise by notional only; convert rather than guess.
            price = request.limit_price or 0.0
            if assessment.approved_notional_usd > 0 and price > 0:
                quantity = assessment.approved_notional_usd / price
        if quantity <= 0:
            raise ExecutionRejected(
                assessment,
                "assessment authorised no quantity, and falling back to the "
                "requested size would bypass the risk gate",
            )

        stop = assessment.adjusted_stop_loss if assessment.adjusted_stop_loss is not None else request.stop_loss
        target = (
            assessment.adjusted_take_profit
            if assessment.adjusted_take_profit is not None
            else request.take_profit
        )

        key = request.idempotency_key or idempotency_key(
            self.config.mode.value, request.symbol, side_value(request.side), new_id()
        )
        return ExecutionInstruction(
            request=request.model_copy(update={"idempotency_key": key}),
            quantity=round(quantity, 10),
            mode=self.config.mode,
            stop_loss=stop,
            take_profit=target,
            leverage=assessment.leverage,
            reason=self._exit_reason,
        )

    # ── Persistence ──────────────────────────────────────────────────────────
    def _persist(
        self,
        request: OrderRequest,
        assessment: RiskAssessment,
        instruction: ExecutionInstruction,
        fill: FillReport,
    ) -> Order:
        """Store the venue's answer so the ledger matches reality."""
        existing = None
        if fill.client_order_id:
            existing = self.orders.by_client_order_id(fill.client_order_id)

        if existing is None:
            order = self.orders.create(
                Order(
                    id=fill.order_id or new_id(),
                    client_order_id=fill.client_order_id or new_id(),
                    symbol=request.symbol,
                    side=request.side,
                    order_type=request.order_type,
                    status=fill.status,
                    quantity=instruction.quantity,
                    filled_quantity=fill.filled_quantity,
                    average_price=fill.average_price,
                    fee_usd=fill.fee_usd,
                    stop_loss=instruction.stop_loss,
                    take_profit=instruction.take_profit,
                    mode=self.config.mode,
                    strategy=request.strategy,
                    signal_id=request.signal_id,
                ),
                signal_id=request.signal_id,
            )
        else:
            order = existing
            order.status = fill.status
            if fill.filled_quantity:
                order.filled_quantity = fill.filled_quantity
            if fill.average_price:
                order.average_price = fill.average_price
            order.fee_usd = max(order.fee_usd, fill.fee_usd)
        self.session.flush()
        return order

    def _record_assessment(
        self,
        request: OrderRequest,
        assessment: RiskAssessment,
        portfolio: PortfolioSnapshot | None,
        *,
        order_id: str | None = None,
    ):
        """Write the decision to the audit trail, whether it allowed or refused."""
        return self.risk.record_assessment(
            assessment,
            symbol=request.symbol,
            side=side_value(request.side),
            mode=self.config.mode.value,
            requested_quantity=request.quantity or 0.0,
            order_id=order_id,
            signal_id=request.signal_id,
            strategy=request.strategy,
            equity=portfolio.equity_usd if portfolio else None,
            drawdown=portfolio.current_drawdown_pct if portfolio else None,
        )

    def _audit_rejection(
        self,
        request: OrderRequest,
        assessment: RiskAssessment,
        portfolio: PortfolioSnapshot | None,
    ) -> None:
        """Record the refusal. A rejection with no trace is indistinguishable from a bug."""
        self._record_assessment(request, assessment, portfolio)
        self.events.log(
            "warning",
            "execution_rejected",
            f"order blocked by risk engine: {'; '.join(assessment.reasons)}",
            context={
                "symbol": request.symbol,
                "side": side_value(request.side),
                "mode": self.config.mode.value,
                "verdict": assessment.verdict.value,
                "failed_rules": assessment.failed_rules,
            },
        )
        self.session.commit()

    def _write_snapshot(self, portfolio: PortfolioSnapshot | None) -> None:
        """Append a portfolio snapshot so the equity curve is continuous."""
        self.portfolio.record_snapshot(
            portfolio.model_copy(update={"mode": self.config.mode})
            if portfolio is not None
            else self.portfolio.build_snapshot(self.config.mode.value)
        )

    def _approval_is_valid(self, request: OrderRequest, approval_id: str) -> bool:
        approval = self.approvals.valid_for(approval_id)
        return approval is not None and approval.is_valid

    # ── Convenience ──────────────────────────────────────────────────────────
    def close_position(
        self,
        symbol: str,
        exit_price: float,
        *,
        reason: str,
        ticker: Ticker,
        quantity: float | None = None,
    ) -> ExecutionOutcome:
        """Flatten an open position through the same gate as any other order.

        Exits are still risk-assessed: a stop-loss must never be blocked by an
        exposure limit, which is why this builds a reducing request rather than
        reusing the entry request.
        """
        position = self.portfolio.get_position(symbol, self.config.mode.value)
        if position is None:
            raise ExecutionRejected(
                RiskAssessment(verdict=RiskVerdict.REJECTED), f"no open position in {symbol}"
            )

        close_quantity = quantity if quantity is not None else position.quantity
        request = OrderRequest(
            symbol=symbol,
            side="sell" if side_value(position.side) == "buy" else "buy",
            order_type="market",
            quantity=close_quantity,
            strategy=position.strategy,
            mode=self.config.mode,
            idempotency_key=idempotency_key("exit", symbol, position.entry_price, exit_price),
        )

        # A protective exit still goes through the engine -- assess_exit applies
        # the exit-side controls (kill switch, circuit breakers, mode, data
        # freshness) while exempting the entry-side admission limits that would
        # otherwise trap the position behind the very cap that created it.
        portfolio = self.portfolio.build_snapshot(self.config.mode.value)
        assessment = self.risk_engine.assess_exit(
            request, portfolio, ticker=ticker, reason=reason
        )
        if not assessment.allowed:
            raise ExecutionRejected(
                assessment,
                f"risk engine refused the {symbol} exit: {'; '.join(assessment.reasons)}",
            )

        self._exit_reason = reason
        try:
            outcome = self.execute(request, assessment, ticker=ticker)
        finally:
            self._exit_reason = None
        logger.info(
            "position_exit",
            symbol=symbol,
            reason=reason,
            price=exit_price,
            quantity=close_quantity,
            status=outcome.status,
        )
        return outcome


def describe_rejection(assessment: RiskAssessment) -> str:
    """A rejection an operator can act on.

    Rule names matter as much as the prose: "max_position_size" tells you which
    knob to turn, the sentence alone does not.
    """
    parts = [
        f"{check.rule}: {check.message}" if check.message else check.rule
        for check in assessment.checks
        if not check.passed
    ]
    detail = "; ".join(parts) or "no reason recorded"
    return f"risk verdict {assessment.verdict.value!r} - {detail}"


def build_paper_executor(session: Session, settings: object) -> OrderExecutor:
    """Wire a paper executor from settings (the common case)."""
    broker = PaperBroker(
        session,
        taker_fee_rate=settings.taker_fee_rate,
        slippage_rate=settings.slippage_rate,
    )
    return OrderExecutor(session, broker, config=ExecutorConfig(mode=TradingMode.PAPER))


__all__ = [
    "ExecutionOutcome",
    "ExecutionRejected",
    "ExecutorConfig",
    "OrderExecutor",
    "build_paper_executor",
]
