# My Finance

Crypto trading research and paper-trading assistant with deterministic technical strategies, recorded AI reviews, hard risk limits, a FastAPI dashboard and optional MCP tools. AI reviews provide context; execution quantities, portfolio accounting and qualification are calculated by code.

## Run locally

Python 3.11+ is required. From this directory:

```bash
make setup
# Edit .env: set a private API_KEY; for local Compose use POSTGRES_HOST=localhost.
make up
make migrate
make seed
make dashboard
```

Open http://127.0.0.1:8000/dashboard/ and http://127.0.0.1:8000/docs. The dashboard has portfolio, equity, signals, trades, AI reviews, strategy evidence, approvals and persistent halt/release controls. Enter your API key and operator name for actions; the key stays in page memory. Serve through authenticated HTTPS before exposing the dashboard or API to a network: read endpoints are local operator endpoints and do not require the mutation key.

For an offline SQLite demo, use a separate file and disable model review explicitly:

```bash
export DATABASE_URL=sqlite:////tmp/my-finance-demo.sqlite
export LLM_ENABLED=false
export TRADING_MODE=paper
python -m src.database.migrate
python -m scripts.seed_database
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

Use your activated virtual environment (`source .venv/bin/activate`) for these Python commands. Synthetic backtests work without exchange connectivity:

```bash
make backtest STRATEGY=breakout SOURCE=synthetic BARS=1500
```

Synthetic candles are demos, never qualification evidence or paper fills. If `LLM_ENABLED=true`, configure `OPENAI_API_KEY`; missing credentials, refusals and malformed model responses reject entries. `LLM_ENABLED=false` enables deterministic paper review. Optional `NEWS_FEED_URLS` is a JSON array of HTTPS RSS/Atom feeds. Without fresh news, sentiment abstains.

## Research and paper trading

Download real history with `make download`. Submit an authenticated backtest from the dashboard with chronological evaluation enabled. It records paired training and held-out runs, costs, data fingerprint and evaluation ID. Strategy evidence checks real data, independent held-out performance, minimum sample, win rate, profit factor, positive expectancy, drawdown and planned reward/risk. A passing research evaluation admits a strategy to paper testing; it does not grant live qualification.

```bash
make paper CYCLES=1
make worker CYCLES=0 INTERVAL=60
make metrics
```

The paper worker processes recorded webhooks and strategy signals. TradingView integration is documented in [the webhook guide](docs/api/tradingview-webhook.md). Queue claims are atomic; uncertain execution attempts remain `processing` for operator reconciliation. Paper promotion additionally requires the configured forward-testing duration, trade sample, returns and drawdown. Promotion is an authenticated operator action; seeding and metrics never bypass evidence. Defaults require 200 research trades, 70% wins, 1.5 profit factor, 2:1 planned reward/risk and 30 days of paper evidence.

Persisted kill-switch controls apply across API and worker processes. Halting blocks new entries; risk-reducing exits remain available. Paper starts with the reference balance seeded into its isolated ledger. Never reuse a research or paper database as a live account ledger.

## Assisted exchange execution

Install `pip install '.[live]'` separately. The automatic worker is paper-only. Testnet/live execution uses `python -m scripts.assisted_trading`: first propose with `--signal SIGNAL_ID --quantity QTY --limit-price PRICE`, approve the exact proposal in the dashboard, then explicitly invoke `--execute APPROVAL_ID`. Approvals expire after 120 seconds and bind symbol, side, quantity, limit, protective levels and mode. Changed economics require a new proposal; consumed approvals cannot be replayed.

Testnet/live requires synthetic fallback disabled, actual exchange credentials and matching sandbox configuration. Live additionally requires both live flags. Entries require enabled, non-degraded AI reviews and qualified strategy evidence; live execution requires human approval regardless of configuration. The implementation supports spot USDT pairs and fails before submission when a venue cannot attach required stop-loss/take-profit protection. Venue-specific protection support must be verified on testnet. Unsupported Binance spot protection combinations are refused, not silently emulated.

Run `python -m scripts.reconcile_exchange` to reconcile locally recorded order fills and actual spot balances. Ledger updates are idempotent and include fees in net P&L. Protective child orders created internally by a venue and external/manual orders require operator reconciliation; they are not automatically imported as local execution records. Uncertain submissions must be checked against venue order history before retrying. Exchange integration was tested with simulated clients, not real credentials or funds.

## MCP

```bash
pip install '.[mcp]'
python -m src.mcp.server
```

The stdio server exposes nine market, portfolio, indicator and research tools. Prices are explicitly timestamped stored candle closes. `MCP_ALLOW_ORDER_TOOLS=false` is the default. When explicitly enabled in paper mode, `create_paper_order` processes a recorded signal through the same review and risk gate. Live execution is never an MCP tool. Send operational logging to stderr; stdout belongs to the protocol.

## Validation and deployment

```bash
make test
make lint
make doctor
# Use only a disposable PostgreSQL database for integration tests:
TEST_DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:PORT/TEST_DB python -m pytest -q tests/integration
```

Integration tests skip unless `TEST_DATABASE_URL` is explicitly set; they create/migrate that database. Existing migration checksums remain unchanged. New migrations repair constraint names and add strategy stages and queue claims. Run migrations as a separate deployment step after backing up your database; this completion does not migrate your configured database automatically. SQLite development files use current metadata; recreate disposable old SQLite demos rather than expecting PostgreSQL ALTER migrations to upgrade them.

The Docker image packages API, workers, scripts and dashboard assets. Compose starts PostgreSQL/Redis separately; its API and worker targets use shared application code. Production deployment, model calls, venue compatibility and long-running strategy profitability require validation in your environment. See [ANALYSIS.md](ANALYSIS.md) for the implementation audit and verified limits.
