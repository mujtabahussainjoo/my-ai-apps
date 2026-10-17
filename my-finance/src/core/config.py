"""Central configuration.

Everything the system can be *tuned* with lives here. Two properties matter
for safety:

1. Values are read from the environment once, validated, and frozen. No module
   reads ``os.environ`` directly.
2. Guardrail settings (``RISK_*``, ``LIVE_TRADING_*``) live next to each other
   so the blast radius of a config change is easy to audit.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

AppEnv = Literal["development", "test", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────────
    app_env: AppEnv = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"  # noqa: S104 - container-facing bind is intended
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000"

    # ── Database ─────────────────────────────────────────────────────────────
    postgres_user: str = "financ"
    postgres_password: SecretStr = SecretStr("change-me-in-production")
    postgres_db: str = "financ"
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    database_url: str | None = None
    redis_url: str = "redis://redis:6379/0"

    # ── LLM ──────────────────────────────────────────────────────────────────
    llm_provider: Literal["openai", "mock"] = "openai"
    llm_enabled: bool = True
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = 45.0
    openai_max_retries: int = 2
    llm_max_output_tokens: int = 1400
    llm_temperature: float = 0.0

    # ── Market data ──────────────────────────────────────────────────────────
    binance_base_url: str = "https://api.binance.com"
    market_data_timeout_seconds: float = 20.0
    market_data_allow_synthetic: bool = True

    # ── Paper / live trading loop ────────────────────────────────────────────
    #: Symbols the loop watches. Kept small on purpose: each one consumes API
    #: quota and, more importantly, an open position's worth of risk budget.
    trading_symbols: list[str] = ["BTC/USDT", "ETH/USDT"]
    trading_timeframe: str = "1h"
    trading_strategies: list[str] = ["breakout", "momentum", "ema_rsi_macd", "mean_reversion"]
    #: Seconds between decision cycles.
    poll_interval_seconds: int = Field(default=60, ge=1, le=86_400)
    #: Cash the paper account starts with.
    starting_equity_usd: float = Field(default=10_000.0, gt=0)
    #: Max cycles to run before exiting; 0 means run until interrupted.
    max_cycles: int = Field(default=0, ge=0)

    # ── Exchange ─────────────────────────────────────────────────────────────
    exchange_id: str = "binance"
    exchange_sandbox: bool = True
    exchange_api_key: SecretStr | None = None
    exchange_api_secret: SecretStr | None = None

    # ── API ──────────────────────────────────────────────────────────────────
    #: Shared key for mutating API routes. None means those routes refuse to
    #: serve at all, which is the safe default for a fresh deployment.
    api_key: SecretStr | None = None
    api_request_log: bool = True

    # ── TradingView webhook ──────────────────────────────────────────────────
    tradingview_webhook_secret: SecretStr | None = None
    webhook_max_body_bytes: int = 8192
    webhook_replay_window_seconds: int = 300

    # ── Risk engine (guardrails) ─────────────────────────────────────────────
    risk_max_position_pct: float = Field(default=5.0, gt=0, le=100)
    risk_max_total_exposure_pct: float = Field(default=40.0, gt=0, le=100)
    risk_max_risk_per_trade_pct: float = Field(default=1.0, gt=0, le=100)
    risk_daily_loss_limit_pct: float = Field(default=3.0, gt=0, le=100)
    risk_max_drawdown_pct: float = Field(default=15.0, gt=0, le=100)
    risk_max_open_positions: int = Field(default=6, ge=1, le=100)
    risk_max_stop_distance_pct: float = Field(default=5.0, gt=0, le=100)
    risk_min_stop_distance_pct: float = Field(default=0.25, gt=0, le=100)
    risk_default_leverage: float = Field(default=1.0, ge=1.0, le=5.0)

    # ── Trading mode ─────────────────────────────────────────────────────────
    trading_mode: Literal["backtest", "paper", "testnet", "live"] = "paper"
    live_trading_enabled: bool = False
    live_trading_i_understand_the_risk: bool = False

    # ── Qualification gate ───────────────────────────────────────────────────
    qualify_min_win_rate: float = Field(default=0.70, ge=0, le=1)
    qualify_min_profit_factor: float = Field(default=1.5, gt=0)
    qualify_max_drawdown: float = Field(default=0.15, gt=0, le=1)
    qualify_min_trades: int = Field(default=200, ge=1)
    qualify_min_risk_reward: float = Field(default=2.0, gt=0)
    qualify_min_paper_days: int = Field(default=30, ge=0)
    qualify_min_paper_trades: int = Field(default=30, ge=0)

    # ── Execution costs ──────────────────────────────────────────────────────
    fee_bps: float = Field(default=10.0, ge=0, le=1000)
    slippage_bps: float = Field(default=5.0, ge=0, le=1000)

    # ── MCP ──────────────────────────────────────────────────────────────────
    mcp_enabled: bool = True
    mcp_allow_order_tools: bool = False
    news_feed_urls: list[str] = []
    news_max_age_hours: int = Field(default=24, ge=1, le=168)

    # ── Derived ──────────────────────────────────────────────────────────────
    @property
    def sqlalchemy_url(self) -> str:
        """Sync SQLAlchemy URL. Overrides win so tests can point at SQLite.

        The ``+psycopg`` driver (not ``+psycopg_async``) is deliberate: the data
        layer is synchronous, so it belongs in the worker and in request handlers
        that offload to a thread, not on the event loop.
        """
        if self.database_url:
            return self.database_url
        return URL.create(
            "postgresql+psycopg",
            username=self.postgres_user,
            password=self.postgres_password.get_secret_value(),
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        ).render_as_string(hide_password=False)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def taker_fee_rate(self) -> float:
        return self.fee_bps / 10_000

    @property
    def slippage_rate(self) -> float:
        return self.slippage_bps / 10_000

    @property
    def round_trip_cost_rate(self) -> float:
        return (self.taker_fee_rate + self.slippage_rate) * 2

    # ── Validators ───────────────────────────────────────────────────────────
    @field_validator("cors_origins")
    @classmethod
    def _reject_wildcard_cors(cls, value: str) -> str:
        if "*" in value:
            raise ValueError(
                "CORS_ORIGINS must not be '*'. Allow-list origins explicitly; "
                "the dashboard needs credentialed requests."
            )
        return value

    @field_validator("postgres_password")
    @classmethod
    def _reject_default_password_in_production(cls, value: SecretStr) -> SecretStr:
        if value.get_secret_value() == "change-me-in-production":
            # Only fatal in production; development keeps the compose default.
            pass
        return value

    @model_validator(mode="after")
    def _guardrail_coherence(self) -> Settings:
        if self.risk_max_risk_per_trade_pct > self.risk_max_position_pct:
            raise ValueError(
                "RISK_MAX_RISK_PER_TRADE_PCT cannot exceed RISK_MAX_POSITION_PCT: "
                "a stop can never be farther than the position it caps."
            )
        if self.risk_min_stop_distance_pct >= self.risk_max_stop_distance_pct:
            raise ValueError("RISK_MIN_STOP_DISTANCE_PCT must be < RISK_MAX_STOP_DISTANCE_PCT.")
        if self.risk_max_total_exposure_pct < self.risk_max_position_pct:
            raise ValueError("RISK_MAX_TOTAL_EXPOSURE_PCT cannot be below RISK_MAX_POSITION_PCT.")
        if self.trading_mode in ("testnet", "live") and self.market_data_allow_synthetic:
            raise ValueError("Synthetic market data is allowed only in paper/backtest mode.")
        if self.app_env == "production":
            if self.trading_mode == "live" and not self.live_trading_enabled:
                raise ValueError("TRADING_MODE=live requires LIVE_TRADING_ENABLED=true.")
            if self.postgres_password.get_secret_value() == "change-me-in-production":
                raise ValueError("POSTGRES_PASSWORD must be changed in production.")
            if self.tradingview_webhook_secret is None:
                raise ValueError("TRADINGVIEW_WEBHOOK_SECRET is required in production.")
        return self

    # ── Secret helpers (never expose the raw value) ──────────────────────────
    def secret(self, name: str) -> str | None:
        """Return a secret's plaintext only for the few call sites that need it."""
        value: SecretStr | None = getattr(self, name, None)
        if value is None:
            return None
        raw = value.get_secret_value()
        return raw or None

    def public_snapshot(self) -> dict[str, object]:
        """Config safe to log or return over the API. Secrets are masked."""
        out: dict[str, object] = {}
        for key, value in self.model_dump().items():
            if key in ("database_url", "redis_url"):
                out[key] = "***masked***"
            elif isinstance(value, SecretStr):
                raw = value.get_secret_value()
                out[key] = "***set***" if raw else None
            else:
                out[key] = value
        out["sqlalchemy_url"] = "***masked***"
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor. Use this, not ``Settings()``."""
    return Settings()
