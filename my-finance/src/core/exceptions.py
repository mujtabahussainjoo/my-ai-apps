"""Typed exception hierarchy.

Every failure mode that crosses a layer boundary has a named type so callers
can branch on behaviour instead of parsing strings. Note the ``fail closed``
family: when a guardrail cannot prove a request is safe, these raise rather
than defaulting to "allowed".
"""

from __future__ import annotations


class MyFinancError(Exception):
    """Base for every domain error raised in this codebase."""


# ── Configuration ───────────────────────────────────────────────────────────
class ConfigurationError(MyFinancError):
    """Invalid or incoherent configuration. Raised at startup."""


class GuardrailMisconfiguration(ConfigurationError):
    """A safety limit is missing or self-contradictory."""


# ── Market data ─────────────────────────────────────────────────────────────
class MarketDataError(MyFinancError):
    """Upstream market-data provider failed."""


class StaleDataError(MarketDataError):
    """Data is too old to trade on. Fail closed rather than act on stale quotes."""


class SymbolNotSupportedError(MarketDataError):
    """Symbol is unknown to the collector or the exchange."""


# ── Analysis ────────────────────────────────────────────────────────────────
class IndicatorError(MyFinancError):
    """Insufficient or invalid data for indicator computation."""


class StrategyError(MyFinancError):
    """Strategy raised during signal generation."""


class StrategyNotFoundError(StrategyError):
    """Unknown strategy name requested from the registry."""


# ── Backtesting ─────────────────────────────────────────────────────────────
class BacktestError(MyFinancError):
    """Backtest could not run."""


class InsufficientDataError(BacktestError):
    """Not enough history to produce a statistically meaningful result."""


# ── Agents / LLM ────────────────────────────────────────────────────────────
class AgentError(MyFinancError):
    """Agent pipeline failure."""


class LLMNotConfiguredError(AgentError):
    """An LLM call was attempted without credentials or with the LLM disabled."""


class StructuredOutputError(AgentError):
    """Model output did not satisfy the required schema.

    Always raised *closed*: the caller must treat the decision as REJECT.
    """


class PromptInjectionError(AgentError):
    """Untrusted text tried to issue instructions to the agent.

    See :mod:`src.core.security` for the detection heuristics.
    """


# ── Risk ────────────────────────────────────────────────────────────────────
class RiskError(MyFinancError):
    """Risk engine failure."""


class RiskRejectedError(RiskError):
    """Guardrail denied the trade. Contains the violated rule."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule
        self.message = message


class TradingHaltedError(RiskError):
    """A circuit breaker (daily loss / drawdown / kill switch) is engaged."""


# ── Execution ───────────────────────────────────────────────────────────────
class ExecutionError(MyFinancError):
    """Order could not be executed."""


class OrderValidationError(ExecutionError):
    """Order failed structural validation before reaching the venue."""


class ApprovalRequiredError(ExecutionError):
    """Live execution attempted without the required human approval."""


class LiveTradingDisabledError(ExecutionError):
    """Live trading is not enabled in configuration.

    Raised unconditionally when ``LIVE_TRADING_ENABLED`` is false, regardless
    of how the request reached this point.
    """


class InsufficientBalanceError(ExecutionError):
    """Wallet cannot cover the order."""


class ExchangeError(ExecutionError):
    """The exchange rejected or failed the request."""


# ── Integrations ────────────────────────────────────────────────────────────
class WebhookError(MyFinancError):
    """Inbound webhook could not be accepted."""


class WebhookAuthError(WebhookError):
    """Webhook signature/secret verification failed."""


class WebhookReplayError(WebhookError):
    """Duplicate or too-old webhook delivery."""


class ValidationError(MyFinancError):
    """Input failed schema or business validation."""
