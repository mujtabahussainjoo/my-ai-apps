For this project, I recommend a **production-style modular monorepo** rather than putting everything into one Python application.

The structure below is designed specifically for your requirements: **GenAI + multi-agent + TA + TradingView + exchange APIs + backtesting + paper trading + testnet + live trading + risk engine + MCP + dashboard**.

```text
my-financ/
│
├── README.md
├── LICENSE
├── .gitignore
├── .env.example
├── docker-compose.yml
├── Makefile
├── pyproject.toml
│
├── docs/
│   ├── architecture/
│   │   ├── system-architecture.md
│   │   ├── agent-architecture.md
│   │   ├── trading-workflow.md
│   │   ├── data-flow.md
│   │   └── security-architecture.md
│   │
│   ├── api/
│   │   ├── api-spec.md
│   │   ├── tradingview-webhook.md
│   │   └── exchange-integration.md
│   │
│   ├── strategies/
│   │   ├── strategy-definition.md
│   │   ├── strategy-rules.md
│   │   └── performance-requirements.md
│   │
│   └── decisions/
│       ├── ADR-001-architecture.md
│       ├── ADR-002-agent-framework.md
│       └── ADR-003-paper-trading.md
│
├── apps/
│   │
│   ├── api/
│   │   ├── main.py
│   │   ├── dependencies.py
│   │   └── routes/
│   │       ├── health.py
│   │       ├── market.py
│   │       ├── signals.py
│   │       ├── strategies.py
│   │       ├── portfolio.py
│   │       ├── trades.py
│   │       ├── backtest.py
│   │       └── tradingview.py
│   │
│   ├── worker/
│   │   ├── main.py
│   │   └── jobs/
│   │       ├── market_data.py
│   │       ├── signal_generation.py
│   │       ├── trade_monitor.py
│   │       ├── strategy_evaluation.py
│   │       └── portfolio_sync.py
│   │
│   └── dashboard/
│       ├── package.json
│       ├── src/
│       │   ├── components/
│       │   ├── pages/
│       │   ├── charts/
│       │   ├── hooks/
│       │   ├── services/
│       │   └── types/
│       └── public/
│
├── src/
│   │
│   ├── agents/
│   │   ├── supervisor/
│   │   │   ├── agent.py
│   │   │   ├── prompts.py
│   │   │   └── state.py
│   │   │
│   │   ├── market/
│   │   │   ├── agent.py
│   │   │   └── prompts.py
│   │   │
│   │   ├── technical/
│   │   │   ├── agent.py
│   │   │   └── prompts.py
│   │   │
│   │   ├── sentiment/
│   │   │   ├── agent.py
│   │   │   └── prompts.py
│   │   │
│   │   ├── risk/
│   │   │   ├── agent.py
│   │   │   └── prompts.py
│   │   │
│   │   └── decision/
│   │       ├── agent.py
│   │       ├── prompts.py
│   │       └── schemas.py
│   │
│   ├── strategies/
│   │   ├── base.py
│   │   ├── registry.py
│   │   ├── ema_rsi_macd.py
│   │   ├── breakout.py
│   │   ├── momentum.py
│   │   └── mean_reversion.py
│   │
│   ├── technical_analysis/
│   │   ├── indicators/
│   │   │   ├── rsi.py
│   │   │   ├── macd.py
│   │   │   ├── ema.py
│   │   │   ├── sma.py
│   │   │   ├── bollinger.py
│   │   │   ├── atr.py
│   │   │   └── adx.py
│   │   │
│   │   ├── support_resistance.py
│   │   ├── trend.py
│   │   └── feature_engine.py
│   │
│   ├── market_data/
│   │   ├── collectors/
│   │   │   ├── binance.py
│   │   │   ├── coinbase.py
│   │   │   └── coingecko.py
│   │   │
│   │   ├── websocket/
│   │   │   ├── binance_ws.py
│   │   │   └── manager.py
│   │   │
│   │   ├── normalization.py
│   │   └── models.py
│   │
│   ├── integrations/
│   │   ├── tradingview/
│   │   │   ├── webhook.py
│   │   │   ├── parser.py
│   │   │   └── schemas.py
│   │   │
│   │   └── exchanges/
│   │       ├── base.py
│   │       ├── ccxt_client.py
│   │       ├── binance.py
│   │       ├── coinbase.py
│   │       └── factory.py
│   │
│   ├── trading/
│   │   ├── execution/
│   │   │   ├── order_manager.py
│   │   │   ├── order_validator.py
│   │   │   └── execution_service.py
│   │   │
│   │   ├── paper/
│   │   │   ├── engine.py
│   │   │   ├── wallet.py
│   │   │   ├── order_simulator.py
│   │   │   ├── position.py
│   │   │   └── pnl.py
│   │   │
│   │   ├── testnet/
│   │   │   └── client.py
│   │   │
│   │   └── live/
│   │       ├── client.py
│   │       └── approval.py
│   │
│   ├── risk/
│   │   ├── risk_engine.py
│   │   ├── position_sizing.py
│   │   ├── exposure.py
│   │   ├── stop_loss.py
│   │   ├── risk_limits.py
│   │   └── portfolio_risk.py
│   │
│   ├── backtesting/
│   │   ├── engine.py
│   │   ├── simulator.py
│   │   ├── data_loader.py
│   │   ├── metrics.py
│   │   └── walk_forward.py
│   │
│   ├── evaluation/
│   │   ├── strategy_evaluator.py
│   │   ├── win_rate.py
│   │   ├── profit_factor.py
│   │   ├── drawdown.py
│   │   ├── sharpe.py
│   │   └── qualification.py
│   │
│   ├── portfolio/
│   │   ├── portfolio_manager.py
│   │   ├── positions.py
│   │   ├── balances.py
│   │   └── performance.py
│   │
│   ├── mcp/
│   │   ├── server.py
│   │   └── tools/
│   │       ├── market_tools.py
│   │       ├── ta_tools.py
│   │       ├── strategy_tools.py
│   │       ├── portfolio_tools.py
│   │       ├── risk_tools.py
│   │       ├── backtest_tools.py
│   │       └── paper_trading_tools.py
│   │
│   ├── llm/
│   │   ├── client.py
│   │   ├── models.py
│   │   ├── prompts/
│   │   │   ├── supervisor.md
│   │   │   ├── market.md
│   │   │   ├── technical.md
│   │   │   ├── risk.md
│   │   │   └── decision.md
│   │   └── structured_output.py
│   │
│   ├── news/
│   │   ├── collector.py
│   │   ├── sentiment.py
│   │   └── models.py
│   │
│   ├── database/
│   │   ├── connection.py
│   │   ├── models/
│   │   │   ├── user.py
│   │   │   ├── market_data.py
│   │   │   ├── strategy.py
│   │   │   ├── signal.py
│   │   │   ├── trade.py
│   │   │   ├── order.py
│   │   │   ├── position.py
│   │   │   └── backtest.py
│   │   └── repositories/
│   │       ├── market_repository.py
│   │       ├── signal_repository.py
│   │       ├── trade_repository.py
│   │       └── strategy_repository.py
│   │
│   ├── core/
│   │   ├── config.py
│   │   ├── constants.py
│   │   ├── enums.py
│   │   ├── exceptions.py
│   │   ├── logging.py
│   │   └── security.py
│   │
│   └── schemas/
│       ├── market.py
│       ├── signal.py
│       ├── order.py
│       ├── trade.py
│       ├── portfolio.py
│       └── risk.py
│
├── tests/
│   ├── unit/
│   │   ├── technical_analysis/
│   │   ├── strategies/
│   │   ├── risk/
│   │   ├── backtesting/
│   │   └── trading/
│   │
│   ├── integration/
│   │   ├── exchanges/
│   │   ├── tradingview/
│   │   ├── agents/
│   │   └── database/
│   │
│   ├── agents/
│   │   ├── supervisor/
│   │   ├── technical/
│   │   ├── market/
│   │   └── risk/
│   │
│   └── fixtures/
│       ├── market_data/
│       └── trading_scenarios/
│
├── data/
│   ├── raw/
│   ├── processed/
│   ├── historical/
│   └── backtests/
│
├── notebooks/
│   ├── 01_market_analysis.ipynb
│   ├── 02_indicator_analysis.ipynb
│   ├── 03_strategy_backtest.ipynb
│   ├── 04_strategy_comparison.ipynb
│   └── 05_paper_trading_analysis.ipynb
│
├── scripts/
│   ├── download_market_data.py
│   ├── run_backtest.py
│   ├── calculate_metrics.py
│   ├── seed_database.py
│   └── start_paper_trading.py
│
├── migrations/
│   └── alembic/
│
├── infrastructure/
│   ├── docker/
│   │   ├── Dockerfile.api
│   │   ├── Dockerfile.worker
│   │   └── Dockerfile.dashboard
│   │
│   ├── nginx/
│   │   └── nginx.conf
│   │
│   └── monitoring/
│       ├── prometheus.yml
│       └── grafana/
│
└── .github/
    └── workflows/
        ├── ci.yml
        ├── tests.yml
        └── deploy.yml
```

## How the major folders map to your requirement

| Folder                      | Responsibility                            |
| --------------------------- | ----------------------------------------- |
| `agents/`                   | AI multi-agent system                     |
| `strategies/`               | Actual deterministic trading strategies   |
| `technical_analysis/`       | RSI, MACD, EMA, ATR, etc.                 |
| `market_data/`              | Binance/Coinbase/CoinGecko data           |
| `integrations/tradingview/` | TradingView webhooks                      |
| `integrations/exchanges/`   | CCXT/exchange integration                 |
| `trading/paper/`            | Your paper-trading engine                 |
| `trading/testnet/`          | Exchange testnet                          |
| `trading/live/`             | Real trading                              |
| `risk/`                     | Hard risk controls                        |
| `backtesting/`              | Historical strategy testing               |
| `evaluation/`               | 70% qualification + performance metrics   |
| `mcp/`                      | Agent-accessible tools                    |
| `llm/`                      | Claude/OpenAI integration                 |
| `portfolio/`                | Portfolio and positions                   |
| `database/`                 | PostgreSQL models/repositories            |
| `dashboard/`                | React/Next.js UI                          |
| `tests/`                    | Automated testing                         |
| `docs/`                     | Architecture and assignment documentation |

### One architectural rule I strongly recommend

Keep these three folders **completely independent**:

```text
src/strategies/
        ↓
src/agents/
        ↓
src/risk/
```

Meaning:

```text
Strategy
  ↓
"BUY candidate"

Agent
  ↓
"Analysis says BUY"

Risk Engine
  ↓
"ALLOWED / REJECTED"
```

The **agent must never bypass `risk/`**, and the strategy should not directly call the exchange.

This separation will make your project look much more like a **real AI engineering/fintech production system** rather than a demo script.
