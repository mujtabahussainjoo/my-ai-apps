"""API tests.

The emphasis is on the refusals. Most of what this API can be asked to do, it
should decline: unauthenticated writes, promotions without evidence, replayed
webhooks. A test suite that only checked the happy path would miss exactly the
behaviour that matters.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("API_KEY", "test-api-key")
os.environ.setdefault("TRADINGVIEW_WEBHOOK_SECRET", "test-webhook-secret")

import apps.api.dependencies as deps  # noqa: E402
import src.database.models  # noqa: F401,E402 - registers the mappers
from apps.api.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import SecretStr  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from src.core.config import Settings  # noqa: E402
from src.core.enums import StrategyStatus  # noqa: E402
from src.database.base import Base  # noqa: E402
from src.database.repositories import StrategyStatusRepository  # noqa: E402
from src.database.seed import ensure_reference_data  # noqa: E402

API_KEY = "test-api-key"
SECRET = "test-webhook-secret"
OPERATOR = {"X-Operator": "alice"}
AUTH = {"X-API-Key": API_KEY}


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    """A client bound to the in-memory session, so tests never touch Postgres.

    Settings are injected rather than read from a module-level snapshot:
    ``get_settings`` is cached process-wide, so whatever loaded first would
    otherwise decide the credentials these tests see.
    """
    deps._engine.dispose()
    test_settings = Settings(
        api_key=SecretStr(API_KEY),
        tradingview_webhook_secret=SecretStr(SECRET),
        trading_mode="paper",
        market_data_allow_synthetic=True,
    )

    def override_session() -> Iterator[Session]:
        yield session

    app = create_app()
    app.dependency_overrides[deps.get_session] = override_session
    app.dependency_overrides[deps.get_settings_dep] = lambda: test_settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    # The replay guards are module-level by design; clear them so one test's
    # recorded alert cannot make the next test's alert look like a replay.
    from apps.api.routes import tradingview

    tradingview._guards.clear()


@pytest.fixture
def seeded(session: Session) -> StrategyStatusRepository:
    ensure_reference_data(session)
    session.commit()
    return StrategyStatusRepository(session)


# ── Read routes ─────────────────────────────────────────────────────────────


class TestReads:
    def test_liveness_does_not_need_the_database(self, client: TestClient):
        assert client.get("/health/live").json()["status"] == "ok"

    def test_symbols_reflect_settings(self, client: TestClient):
        body = client.get("/market/symbols").json()
        assert body["symbols"]
        assert body["timeframe"]

    def test_portfolio_reports_cash(self, client: TestClient, seeded):
        body = client.get("/portfolio").json()
        assert "equity_usd" in body
        assert body["mode"] == "paper"

    def test_an_unknown_mode_is_rejected(self, client: TestClient, seeded):
        assert client.get("/portfolio", params={"mode": "yolo"}).status_code == 422

    def test_strategies_list_every_registered_strategy(self, client: TestClient, seeded):
        body = client.get("/strategies").json()
        names = {s["strategy"] for s in body["strategies"]}
        assert {"breakout", "momentum", "ema_rsi_macd", "mean_reversion"} <= names

    def test_an_unknown_strategy_is_a_404(self, client: TestClient, seeded):
        assert client.get("/strategies/does_not_exist").status_code == 404

    def test_candles_for_an_unstored_symbol_are_empty_not_an_error(self, client: TestClient, seeded):
        body = client.get("/market/candles", params={"symbol": "NOPE/USDT", "timeframe": "1h"}).json()
        assert body["count"] == 0

    def test_an_unknown_timeframe_is_a_422(self, client: TestClient, seeded):
        assert (
            client.get("/market/candles", params={"symbol": "BTC/USDT", "timeframe": "7y"}).status_code == 422
        )


# ── Authentication ──────────────────────────────────────────────────────────


class TestAuthentication:
    def test_qualifying_without_a_key_is_refused(self, client: TestClient, seeded):
        response = client.post(
            "/strategies/breakout/qualification",
            json={"qualified": False, "reason": "revoking for a test here"},
        )
        assert response.status_code == 401

    def test_a_wrong_key_is_refused(self, client: TestClient, seeded):
        response = client.post(
            "/strategies/breakout/qualification",
            headers={"X-API-Key": "not-the-key"},
            json={"qualified": False, "reason": "revoking with a bad key"},
        )
        assert response.status_code == 401

    def test_a_qualification_change_needs_a_named_operator(self, client: TestClient, seeded):
        response = client.post(
            "/strategies/breakout/qualification",
            headers=AUTH,
            json={"qualified": False, "reason": "revoking without attribution"},
        )
        assert response.status_code == 400
        assert "X-Operator" in response.json()["detail"]

    def test_a_short_reason_is_rejected(self, client: TestClient, seeded):
        response = client.post(
            "/strategies/breakout/qualification",
            headers={**AUTH, **OPERATOR},
            json={"qualified": False, "reason": "nope"},
        )
        assert response.status_code == 422

    def test_revoking_a_strategy_works_and_is_attributed(self, client: TestClient, seeded):
        seeded.set("breakout", StrategyStatus.QUALIFIED, qualified=True)
        seeded.session.commit()

        response = client.post(
            "/strategies/breakout/qualification",
            headers={**AUTH, **OPERATOR},
            json={"qualified": False, "reason": "revoked because the edge decayed"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["qualified"] is False
        assert body["status"] == StrategyStatus.CANDIDATE.value
        assert body["changed_by"] == "alice"

    def test_qualifying_without_backtest_evidence_is_refused(self, client: TestClient, seeded):
        response = client.post(
            "/strategies/momentum/qualification",
            headers={**AUTH, **OPERATOR},
            json={"qualified": True, "reason": "this strategy looks promising to me"},
        )
        assert response.status_code == 409
        assert "no recorded backtest" in response.json()["detail"]


# ── Webhooks ────────────────────────────────────────────────────────────────


class TestWebhook:
    def test_a_wrong_secret_is_refused(self, client: TestClient, seeded):
        response = client.post(
            "/webhooks/tradingview",
            headers={"X-Webhook-Secret": "wrong"},
            json={"symbol": "BTC/USDT", "action": "buy", "price": 100.0},
        )
        assert response.status_code == 401

    def test_a_valid_alert_is_recorded(self, client: TestClient, seeded):
        response = client.post(
            "/webhooks/tradingview",
            headers={"X-Webhook-Secret": SECRET},
            json={
                "symbol": "BINANCE:BTCUSDT",
                "action": "buy",
                "price": 60000.0,
                "stop_loss": 59000.0,
                "take_profit": 62000.0,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "recorded"
        # TradingView's exchange-prefixed form is normalised.
        assert body["symbol"] == "BTC/USDT"

    def test_a_replayed_alert_is_refused(self, client: TestClient, seeded):
        payload = {"symbol": "BTC/USDT", "action": "buy", "price": 100.0, "confidence": 0.6}
        headers = {"X-Webhook-Secret": SECRET}
        assert client.post("/webhooks/tradingview", headers=headers, json=payload).status_code == 200
        assert client.post("/webhooks/tradingview", headers=headers, json=payload).status_code == 409

    def test_an_unparseable_action_is_refused(self, client: TestClient, seeded):
        response = client.post(
            "/webhooks/tradingview",
            headers={"X-Webhook-Secret": SECRET},
            json={"symbol": "BTC/USDT", "action": "moon", "price": 100.0},
        )
        assert response.status_code == 422

    def test_a_hold_alert_is_ignored_rather_than_recorded(self, client: TestClient, seeded):
        response = client.post(
            "/webhooks/tradingview",
            headers={"X-Webhook-Secret": SECRET},
            json={"symbol": "SOL/USDT", "action": "hold", "price": 150.0},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    def test_an_alert_without_a_price_is_refused(self, client: TestClient, seeded):
        response = client.post(
            "/webhooks/tradingview",
            headers={"X-Webhook-Secret": SECRET},
            json={"symbol": "SOL/USDT", "action": "buy"},
        )
        assert response.status_code == 422

    def test_the_secret_may_travel_in_the_body(self, client: TestClient, seeded):
        """The documented form: TradingView cannot set custom headers."""
        response = client.post(
            "/webhooks/tradingview",
            json={
                "secret": SECRET,
                "symbol": "BTC/USDT",
                "action": "buy",
                "price": 60000.0,
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "recorded"

    def test_a_body_secret_is_not_echoed_back(self, client: TestClient, seeded):
        response = client.post(
            "/webhooks/tradingview",
            json={
                "secret": SECRET,
                "symbol": "BTC/USDT",
                "action": "buy",
                "price": 60000.0,
            },
        )
        assert SECRET not in response.text

    def test_the_body_secret_is_not_stored(self, client: TestClient, seeded):
        client.post(
            "/webhooks/tradingview",
            json={
                "secret": SECRET,
                "symbol": "BTC/USDT",
                "action": "buy",
                "price": 60000.0,
                "confidence": 0.7,
            },
        )
        body = client.get("/signals", params={"limit": 5}).text
        assert SECRET not in body

    def test_a_wrong_body_secret_is_refused(self, client: TestClient, seeded):
        response = client.post(
            "/webhooks/tradingview",
            json={
                "secret": "not-the-secret",
                "symbol": "BTC/USDT",
                "action": "buy",
                "price": 60000.0,
            },
        )
        assert response.status_code == 401

    def test_a_malformed_body_is_refused(self, client: TestClient, seeded):
        response = client.post(
            "/webhooks/tradingview",
            headers={"X-Webhook-Secret": SECRET, "Content-Type": "application/json"},
            content=b"{not json at all",
        )
        assert response.status_code == 422

    def test_a_non_object_body_is_refused(self, client: TestClient, seeded):
        response = client.post(
            "/webhooks/tradingview",
            headers={"X-Webhook-Secret": SECRET, "Content-Type": "application/json"},
            content=b"[1, 2, 3]",
        )
        assert response.status_code == 422

    def test_a_body_secret_and_header_secret_are_the_same_alert(self, client: TestClient, seeded):
        """One alert, two transports: the replay guard must still catch it."""
        payload = {"symbol": "BTC/USDT", "action": "buy", "price": 4242.0}
        assert (
            client.post(
                "/webhooks/tradingview", headers={"X-Webhook-Secret": SECRET}, json=payload
            ).status_code
            == 200
        )
        # Same alert re-sent with the secret in the body instead of the header.
        # The fingerprint is taken after stripping it, so the retry is caught.
        assert client.post("/webhooks/tradingview", json={"secret": SECRET, **payload}).status_code == 409

    def test_the_webhook_never_places_an_order(self, client: TestClient, seeded):
        """The whole point: an alert is data, not an instruction to trade."""
        client.post(
            "/webhooks/tradingview",
            headers={"X-Webhook-Secret": SECRET},
            json={
                "symbol": "AVAX/USDT",
                "action": "buy",
                "price": 25.0,
                "stop_loss": 24.0,
                "take_profit": 28.0,
                "strategy": "breakout",
            },
        )
        orders = client.get("/orders").json()
        assert orders["count"] == 0


# ── Backtests ───────────────────────────────────────────────────────────────


class TestBacktestRoutes:
    def test_an_unknown_strategy_is_refused(self, client: TestClient, seeded):
        response = client.post("/backtest", headers=AUTH, json={"strategy": "moon_phase", "bars": 400})
        assert response.status_code == 404

    def test_too_few_bars_is_refused(self, client: TestClient, seeded):
        response = client.post("/backtest", headers=AUTH, json={"strategy": "breakout", "bars": 10})
        assert response.status_code == 422

    def test_an_unknown_run_is_a_404(self, client: TestClient, seeded):
        assert client.get("/backtest/nope").status_code == 404


# ── Prometheus metrics ──────────────────────────────────────────────────────


class TestMetrics:
    """The monitoring stack scrapes this; a broken format is a silent outage."""

    def test_metrics_are_plain_text_not_json(self, client: TestClient):
        response = client.get("/metrics")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        # A JSON-quoted body is the failure mode this guards against.
        assert not response.text.startswith('"')

    def test_metrics_parse_as_exposition_format(self, client: TestClient, seeded):
        client.get("/portfolio")  # ensure a snapshot exists
        body = client.get("/metrics").text
        pairs = [
            line.split()[0:2]
            for line in body.splitlines()
            if line and not line.startswith("#") and len(line.split()) == 2
        ]
        assert pairs, "no samples were exported"
        for name, value in pairs:
            float(value)  # every sample value must be numeric
            assert name.startswith("financ_")

    def test_every_series_is_declared_before_use(self, client: TestClient, seeded):
        body = client.get("/metrics").text
        declared = {line.split()[2] for line in body.splitlines() if line.startswith("# HELP")}
        used = {line.split()[0] for line in body.splitlines() if line and not line.startswith("#")}
        assert used <= declared, f"undeclared series: {used - declared}"

    def test_the_service_is_up_even_before_anything_has_traded(self, client: TestClient):
        """A fresh database must not look like an outage."""
        body = client.get("/metrics").text
        assert "financ_up 1" in body
        # ...but the absence of a snapshot is visible in its own right.
        assert "financ_has_snapshot 0" in body

    def test_live_trading_is_visible_as_a_metric(self, client: TestClient, seeded):
        assert "financ_trading_mode_active 0" in client.get("/metrics").text

    def test_metrics_never_leak_a_secret(self, client: TestClient, seeded):
        body = client.get("/metrics").text
        assert SECRET not in body
        assert API_KEY not in body


# ── Cross-cutting ───────────────────────────────────────────────────────────


class TestCrossCutting:
    def test_every_response_carries_a_request_id(self, client: TestClient):
        assert client.get("/health/live").headers["X-Request-ID"]

    def test_a_supplied_request_id_is_preserved(self, client: TestClient):
        response = client.get("/health/live", headers={"X-Request-ID": "abc123"})
        assert response.headers["X-Request-ID"] == "abc123"

    def test_the_openapi_document_builds(self, client: TestClient):
        """A broken schema would otherwise only surface at deploy time."""
        spec = client.get("/openapi.json").json()
        assert "/health/live" in spec["paths"]
        assert "/strategies/{name}/qualification" in spec["paths"]
