"""Operator-driven testnet/live execution, with durable exact-order approval."""

from datetime import UTC, datetime

from sqlalchemy import select

from src.agents.supervisor.agent import Supervisor
from src.core.enums import OrderSide, OrderType, SignalAction, StrategyStatus, TradingMode
from src.core.exceptions import ExecutionError
from src.database.models.audit import SystemEvent
from src.database.repositories import (
    ApprovalRepository,
    PortfolioRepository,
    SignalRepository,
    StrategyStatusRepository,
    SystemEventRepository,
)
from src.portfolio.manager import PortfolioManager
from src.risk.risk_engine import RiskEngine
from src.schemas.market import Ticker
from src.schemas.order import OrderRequest
from src.trading.approval import order_fingerprint
from src.trading.executor import ExecutionRejected, ExecutorConfig, OrderExecutor
from src.trading.live.broker import ExchangeBroker


class AssistedTrading:
    def __init__(self, session, settings, *, broker=None, supervisor=None):
        self.session, self.settings = session, settings
        self.mode = TradingMode(settings.trading_mode)
        if self.mode not in (TradingMode.TESTNET, TradingMode.LIVE):
            raise ValueError("assisted exchange execution requires testnet or live configuration")
        self.broker = broker or ExchangeBroker.from_settings(settings)
        self.supervisor = supervisor or Supervisor(settings)
        self.risk = RiskEngine(settings)
        self.portfolio = PortfolioManager(session, self.broker)
        self.signals = SignalRepository(session)
        self.strategies = StrategyStatusRepository(session)
        self.approvals = ApprovalRepository(session)
        self.events = SystemEventRepository(session)
        self.executor = OrderExecutor(
            session, self.broker, config=ExecutorConfig(mode=self.mode), risk_engine=self.risk
        )

    def quote(self, symbol):
        raw = self.broker._client.fetch_ticker(symbol)
        if not raw.get("timestamp"):
            raise ExecutionError("venue quote has no timestamp")
        return Ticker(
            symbol=symbol,
            last=raw["last"],
            bid=raw.get("bid"),
            ask=raw.get("ask"),
            timestamp=datetime.fromtimestamp(raw["timestamp"] / 1000, UTC),
        )

    def assess(self, request):
        if not request.symbol.endswith("/USDT") or request.leverage != 1:
            raise ExecutionError("assisted execution supports unleveraged USDT spot pairs")
        # Unknown resting orders can reserve exposure absent from the local ledger.
        if self.broker.poll_open_orders():
            raise ExecutionError("reconcile outstanding exchange orders before proposing another order")
        portfolio = self.portfolio.sync()
        ticker = self.quote(request.symbol)
        signal = self.signals.get(request.signal_id) if request.signal_id else None
        if signal is None:
            raise ExecutionError("a recorded deterministic signal is required")
        if (
            signal.symbol != request.symbol
            or signal.strategy != request.strategy
            or (signal.action is SignalAction.BUY) != (request.side is OrderSide.BUY)
        ):
            raise ExecutionError("request does not match its recorded signal")
        if abs(ticker.last - request.limit_price) / request.limit_price > 0.01:
            raise ExecutionError("quote moved more than 1% from the proposed limit; propose again")
        position = PortfolioRepository(self.session).get_position(request.symbol, self.mode.value)
        if request.side is OrderSide.SELL:
            if position is None:
                raise ExecutionError("spot sell must reduce an existing position")
            assessment = self.risk.assess_exit(request, portfolio, ticker=ticker, reason="manual")
        else:
            if not self.settings.llm_enabled:
                raise ExecutionError("exchange entries require an enabled AI review")
            review = self.supervisor.analyse(signal, ticker=ticker, portfolio=portfolio, session=self.session)
            row = self.strategies.get(request.strategy)
            status = StrategyStatus(row.status) if row else StrategyStatus.CANDIDATE
            assessment = self.risk.assess(
                request,
                portfolio,
                ticker=ticker,
                signal=signal,
                strategy_status=status,
                agent_approved=self.supervisor.approved(review),
                atr=signal.atr,
            )
        if not assessment.allowed:
            self.executor._audit_rejection(request, assessment, portfolio)
            raise ExecutionRejected(assessment)
        effective = request.model_copy(
            update={
                "quantity": assessment.approved_quantity,
                "notional_usd": None,
                "stop_loss": assessment.adjusted_stop_loss
                if assessment.adjusted_stop_loss is not None
                else request.stop_loss,
                "take_profit": assessment.adjusted_take_profit
                if assessment.adjusted_take_profit is not None
                else request.take_profit,
            }
        )
        return effective, assessment, ticker, portfolio

    def propose(self, signal_id, quantity, limit_price):
        signal = self.signals.get(signal_id)
        if signal is None:
            raise ValueError("signal not found")
        request = OrderRequest(
            symbol=signal.symbol,
            side="buy" if signal.action is SignalAction.BUY else "sell",
            order_type=OrderType.LIMIT,
            quantity=quantity,
            limit_price=limit_price,
            stop_loss=signal.stop_loss if signal.action is SignalAction.BUY else None,
            take_profit=signal.take_profit if signal.action is SignalAction.BUY else None,
            strategy=signal.strategy,
            signal_id=signal_id,
            mode=self.mode,
        )
        effective, assessment, ticker, _ = self.assess(request)
        approval = self.approvals.request(order_fingerprint(effective))
        self.events.log(
            "assisted",
            "order_proposed",
            "Operator approval requested",
            context={
                "approval_id": approval.id,
                "request": effective.model_dump(mode="json"),
                "assessment": assessment.model_dump(mode="json"),
                "quote": ticker.model_dump(mode="json"),
            },
        )
        self.session.commit()
        return {
            "approval_id": approval.id,
            "request": effective.model_dump(mode="json"),
            "assessment": assessment.model_dump(mode="json"),
        }

    def execute(self, approval_id):
        events = self.session.scalars(
            select(SystemEvent)
            .where(SystemEvent.component == "assisted", SystemEvent.event == "order_proposed")
            .order_by(SystemEvent.id.desc())
        )
        event = next((e for e in events if e.context and e.context.get("approval_id") == approval_id), None)
        if event is None:
            raise ValueError("no recorded proposal for approval")
        original = OrderRequest.model_validate(event.context["request"])
        effective, assessment, ticker, portfolio = self.assess(original)
        if order_fingerprint(effective) != order_fingerprint(original):
            raise ExecutionError("risk-approved economics changed; request a new approval")
        effective = effective.model_copy(update={"idempotency_key": "approval-" + approval_id})
        outcome = self.executor.execute(
            effective, assessment, ticker=ticker, portfolio=portfolio, approval_id=approval_id
        )
        self.portfolio.sync()
        return {"order_id": outcome.order_id, "status": outcome.status, "detail": outcome.detail}
