Yes. For this assignment, I would **not make the LLM itself responsible for deciding trades**. Build a proper trading system where deterministic TA/quant logic generates signals, an AI agent analyzes/contextualizes them, and a separate risk engine decides whether an order is allowed.

The key requirement should be:

> **Only promote a strategy to live trading if its out-of-sample/backtest + paper-trading performance meets predefined criteria, including ≥70% win rate, while also checking profit factor, drawdown, and risk-adjusted returns.**

A 70% win rate alone is not enough—for example, a strategy can win 70 trades out of 100 and still lose money if the 30 losses are much larger.

---

# 1. Overall architecture

```text
                   ┌─────────────────────┐
                   │   Market Data APIs   │
                   │ Binance / Coinbase  │
                   │ CoinGecko / etc.     │
                   └──────────┬──────────┘
                              │
                              ▼
                   ┌─────────────────────┐
                   │  Data Normalization │
                   │ OHLCV / Order Book  │
                   │ Volume / Funding    │
                   └──────────┬──────────┘
                              │
             ┌────────────────┴────────────────┐
             ▼                                 ▼
    ┌──────────────────┐              ┌──────────────────┐
    │ Technical Engine │              │ Market Context   │
    │                  │              │                  │
    │ RSI              │              │ News             │
    │ MACD             │              │ Sentiment        │
    │ EMA/SMA          │              │ Fear & Greed     │
    │ Bollinger        │              │ BTC dominance    │
    │ Volume           │              │ Funding/OI        │
    │ Support/Resist.  │              │                  │
    └────────┬─────────┘              └────────┬─────────┘
             │                                 │
             └──────────────┬──────────────────┘
                            ▼
                 ┌──────────────────────┐
                 │   SIGNAL ENGINE      │
                 │                      │
                 │ BUY / SELL / HOLD    │
                 │ Entry                │
                 │ Stop Loss            │
                 │ Take Profit          │
                 │ Confidence           │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │   AI AGENT           │
                 │                      │
                 │ Analyze signal       │
                 │ Check market context │
                 │ Explain reasoning    │
                 │ Challenge signal     │
                 └──────────┬───────────┘
                            │
                            ▼
                 ┌──────────────────────┐
                 │    RISK ENGINE       │
                 │                      │
                 │ Position size        │
                 │ Max loss             │
                 │ Exposure             │
                 │ Daily loss limit     │
                 │ Correlation          │
                 └──────────┬───────────┘
                            │
                    ┌───────┴────────┐
                    ▼                ▼
              PAPER MODE         LIVE MODE
                    │                │
                    ▼                ▼
             Paper Exchange     Real Exchange
                    │                │
                    └───────┬────────┘
                            ▼
                  ┌──────────────────┐
                  │ Trade Monitor    │
                  │ P&L              │
                  │ Win Rate         │
                  │ Drawdown         │
                  │ Sharpe           │
                  │ Profit Factor    │
                  └────────┬─────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │ Evaluation/ML    │
                  │ Improve strategy │
                  └──────────────────┘
```

---

# 2. Most important design principle

I recommend **3 separate layers**.

### Layer 1 — Quant/TA engine

This answers:

> "Is there a trading setup?"

Example:

```text
BTC/USDT

RSI = 28
EMA20 > EMA50
MACD bullish crossover
Volume increasing
Price near support

        ↓

Signal = BUY
```

This should be **Python code**, not an LLM.

---

### Layer 2 — AI Agent

The agent answers:

> "Given this setup and the current context, should we allow this trade?"

It receives structured information:

```json
{
  "symbol": "BTC/USDT",
  "signal": "BUY",
  "rsi": 28,
  "macd": "bullish",
  "ema_trend": "bullish",
  "volume": "high",
  "support": 62500,
  "entry": 62800,
  "stop_loss": 61500,
  "take_profit": 65500
}
```

Then the agent can analyze:

```text
Technical setup:      GOOD
Market trend:         GOOD
Volume confirmation:  GOOD
News risk:            MEDIUM
BTC volatility:       HIGH
Risk/reward:          2.4

Decision:

APPROVE
Confidence: 82%
```

But **the AI should not have direct unrestricted access to place orders**.

---

# 3. Layer 3 — Risk Engine

This is extremely important.

Even if the AI says:

```text
BUY BTC
```

the risk engine can say:

```text
REJECT

Reason:
Maximum portfolio exposure exceeded.
```

So:

```text
AI says BUY
       ↓
Risk Engine
       ↓
Allowed?
   /       \
 NO         YES
 │           │
STOP       Execute
```

This makes the architecture much safer.

---

# 4. Trading modes

Your assignment should explicitly support **three modes**.

```text
              TRADING ENGINE
                    │
        ┌───────────┼───────────┐
        │           │           │
        ▼           ▼           ▼
     BACKTEST     PAPER       LIVE
```

### Mode 1 — Backtest

Historical data.

```text
2021 ─────────────── 2025
          ↓
      Strategy
          ↓
     1,000 trades
          ↓
Win rate = 73%
Profit Factor = 1.9
Max DD = 12%
```

---

### Mode 2 — Paper trading

Real-time market data but fake money.

Example:

```text
Virtual Capital = $10,000

BUY BTC
Entry = $62,000
Quantity = 0.05 BTC

No real money involved.
```

This is critical before live trading.

Binance provides Spot and Futures Testnets specifically for testing with virtual assets. Binance notes that testnet balances/assets are not real and that the testnet can periodically reset. ([Binance][1])

---

### Mode 3 — Live

Only after passing your validation gates:

```text
BACKTEST
   ↓
PAPER
   ↓
LIVE
```

I would **never allow the agent to automatically switch from paper → live**.

Make live mode an explicit human-controlled setting.

---

# 5. Your 70% requirement

Don't implement:

```python
if win_rate > 70:
    trade()
```

That's too simplistic.

Use something like:

```text
Strategy qualification

Win Rate              >= 70%
Profit Factor         >= 1.5
Maximum Drawdown      <= 15%
Minimum Trades        >= 200
Risk/Reward           >= 1:2
Paper Trading         >= 30 days
Out-of-sample result  >= threshold
```

For example:

```text
Strategy A

Backtest:
Trades          850
Win Rate        74.2%
Profit Factor   1.82
Max Drawdown    11.4%

Paper:
Trades          137
Win Rate        71.5%
Profit Factor   1.67

STATUS
──────
✅ Approved for consideration
```

This is much stronger than claiming:

> "AI predicts crypto with 70% accuracy."

---

# 6. TradingView integration

TradingView is very useful for your architecture.

TradingView alerts can send an HTTP POST webhook to your application when an alert triggers. The webhook can contain JSON, making it suitable for your signal-ingestion service. ([TradingView][2])

```text
TradingView
    │
    │ Webhook  (POST /webhooks/tradingview)
    ▼
┌────────────────────────────┐
│ Verified, recorded as a    │  an alert is DATA, never an order
│ signal, status = pending   │
└─────────────┬──────────────┘
              │  worker drains the queue
              ▼
┌────────────────────────────┐
│ Trigger: re-evaluate the   │  the alert's price/stop are advisory
│ qualified strategies       │  and are anchored to the live price
└─────────────┬──────────────┘
              │
              ▼
     strategy signal  →  RiskEngine  →  order
```

### An alert is a trigger, not an instruction

TradingView cannot set custom headers, so a real alert authenticates with a
shared secret in the JSON body (`"secret"`); a header is also accepted.

An alert carries a symbol and a direction. It does not carry a qualified
strategy, a defensible stop, or a size that respects a risk budget. So when an
alert names no strategy of ours, the worker does not trade its numbers. It asks
the qualified strategies what *they* see on that symbol, and the strategy that
produces a signal supplies its own entry, stop and size. Any resulting order is
linked to that strategy signal, not to the alert.

This keeps the one invariant that matters: every order in the ledger traces back
to deterministic reasoning, never to whoever configured the alert. An alert can
make the system look sooner; it cannot make it trade differently.

If an alert *does* name one of our strategies, that signal is judged on its own
merits - and its protective levels are still replaced when they are tighter than
volatility justifies, because a tighter stop means a larger position.

Example payload:

```json
{
  "symbol": "BTCUSDT",
  "exchange": "BINANCE",
  "timeframe": "1h",
  "signal": "BUY",
  "price": 62800,
  "strategy": "EMA_RSI_MACD"
}
```

Your backend receives it.

---

# 7. APIs I would use

## A. Market data

### TradingView

Use for:

```text
Charts
Indicators
Alerts
Trading signals
Technical analysis
Webhook events
```

TradingView supports alerts on data series, indicators, strategy orders and drawing objects. ([TradingView][3])

---

### CoinGecko

Use for:

```text
Coin metadata
Market data
Market cap
Volume
Coin information
Historical data
```

Good as a supplementary market-data source.

---

### Exchange APIs

For actual trading you need exchange APIs.

For example:

```text
Binance
Coinbase
Kraken
Bybit
OKX
```

---

# 8. Use CCXT

For your assignment, I strongly recommend:

```text
Python
   ↓
CCXT
   ↓
Exchange APIs
```

Instead of writing:

```text
Binance integration
Coinbase integration
Kraken integration
Bybit integration
...
```

CCXT gives you a unified API across many cryptocurrency exchanges and supports market data, balances, orders and other trading functionality. It also supports sandbox/testnet mode where an exchange provides one. ([CCXT][4])

Example:

```python
import ccxt

exchange = ccxt.binance({
    "apiKey": API_KEY,
    "secret": API_SECRET
})

ticker = exchange.fetch_ticker("BTC/USDT")

print(ticker["last"])
```

Then:

```text
Trading Engine
      ↓
     CCXT
      ↓
 ┌────┴─────┐
 │          │
Binance   Coinbase
```

---

# 9. Data pipeline

I would build this first:

```text
Exchange WebSocket
        ↓
Market Data Service
        ↓
Redis
        ↓
Time-series DB
        ↓
Feature Engine
```

Store:

```text
timestamp
symbol
open
high
low
close
volume
```

And potentially:

```text
order book
funding rate
open interest
liquidations
trades
```

---

# 10. Technical Analysis engine

Create a separate Python service.

Example:

```text
TA Engine

├── RSI
├── MACD
├── EMA
├── SMA
├── Bollinger Bands
├── ATR
├── ADX
├── Volume
├── Support/Resistance
└── Trend Detection
```

For example:

```python
features = {
    "rsi": 28,
    "macd": "bullish",
    "ema20": 63000,
    "ema50": 62000,
    "atr": 1200,
    "volume_ratio": 1.8
}
```

---

# 11. Strategy engine

Don't put everything into one strategy.

Create multiple strategies.

```text
Strategy Engine
       │
       ├── Trend Following
       ├── Momentum
       ├── Mean Reversion
       ├── Breakout
       └── Multi Indicator
```

Example:

```text
Strategy #1

IF

RSI < 30
AND
EMA20 > EMA50
AND
MACD bullish
AND
Volume > average volume

THEN

BUY
```

Then backtest it.

---

# 12. Strategy registry

This is a very useful feature for your assignment.

Create:

```text
Strategy Registry
```

Example:

| Strategy       | Win Rate | Profit Factor | Drawdown | Status |
| -------------- | -------: | ------------: | -------: | ------ |
| EMA + RSI      |      73% |           1.8 |      11% | ✅      |
| MACD           |      64% |           1.2 |      21% | ❌      |
| Breakout       |      72% |           1.6 |      14% | ✅      |
| Mean Reversion |      58% |           0.9 |      25% | ❌      |

Then your AI agent can select only **qualified strategies**.

---

# 13. AI Agent architecture

I would actually use multiple agents.

```text
                   Supervisor Agent
                         │
          ┌──────────────┼───────────────┐
          ▼              ▼               ▼
     Market Agent    TA Agent       Risk Agent
          │              │               │
          ▼              ▼               ▼
      News/Data       Indicators      Portfolio
          │              │               │
          └──────────────┼───────────────┘
                         ▼
                  Decision Agent
                         │
                         ▼
                   Trade Proposal
                         │
                         ▼
                    Risk Engine
                         │
                    ┌────┴────┐
                    ▼         ▼
                  PAPER      LIVE
```

---

# 14. What each agent does

### Market Agent

Collects:

```text
Price
Volume
Volatility
Funding
Open Interest
Market regime
```

---

### TA Agent

Analyzes:

```text
RSI
MACD
EMA
Trend
Support
Resistance
Breakout
Momentum
```

---

### News/Sentiment Agent

Checks:

```text
News
Major announcements
Regulatory events
ETF-related news
Exchange incidents
Market sentiment
```

---

### Risk Agent

Checks:

```text
Portfolio exposure
Position size
Stop loss
Maximum loss
Correlation
Existing positions
Daily loss
```

---

### Decision Agent

Combines everything.

Example:

```text
TA                 80%
Market             75%
Sentiment          62%
Risk               90%

Final confidence   81%
```

Then:

```text
BUY
```

or:

```text
NO TRADE
```

---

# 15. Very important: don't let the LLM calculate everything

Bad architecture:

```text
Price → LLM → BUY
```

Better:

```text
Market Data
    ↓
Quant/TA
    ↓
Structured Features
    ↓
LLM Agent
    ↓
Risk Engine
    ↓
Execution
```

The LLM is excellent for:

```text
reasoning
summarization
explanation
context
agent orchestration
```

It should not be your primary mathematical trading engine.

---

# 16. Trading call output

Your application could display:

```text
━━━━━━━━━━━━━━━━━━━━━━
BTC/USDT
1 Hour
━━━━━━━━━━━━━━━━━━━━━━

Signal       🟢 BUY

Entry
$62,500 – $63,000

Stop Loss
$61,200

TP1
$65,000

TP2
$67,500

Risk/Reward
1 : 2.4

Strategy
EMA + RSI + MACD

Historical Win Rate
73.4%

Backtest Trades
842

Confidence
81%

Market Regime
Bullish

Risk
Medium

Status
PAPER TRADE
━━━━━━━━━━━━━━━━━━━━━━
```

And most importantly:

```text
WHY?

✓ RSI oversold
✓ Bullish MACD crossover
✓ EMA trend positive
✓ Volume confirmation
✓ Support holding

RISKS

⚠ High volatility
⚠ BTC approaching resistance
```

---

# 17. Paper trading engine

Don't rely exclusively on an exchange testnet.

Build your **own paper trading engine** too.

```text
Real-time market price
        ↓
Paper Order Engine
        ↓
Virtual Wallet
        ↓
Virtual Orders
        ↓
Virtual Positions
        ↓
P&L
```

Example:

```text
Initial Balance

$10,000

BUY BTC

Entry       $62,000
Quantity    0.05
Investment  $3,100
SL          $60,800
TP          $65,000
```

Then your engine monitors real prices.

---

# 18. Paper vs Testnet

Use both.

```text
                 TESTING
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
   Internal Paper       Exchange Testnet
          │                   │
          │                   │
   Test your logic       Test API/orders
```

### Internal paper trading

Best for:

```text
Strategy validation
Agent testing
Risk testing
Performance measurement
```

### Exchange testnet

Best for:

```text
API integration
Order placement
Order cancellation
Authentication
Exchange behavior
```

Binance specifically provides Spot and Futures testnets for testing functions with virtual assets. ([Binance][1])

---

# 19. Backtesting architecture

You should have:

```text
Historical Data
      ↓
Feature Generator
      ↓
Strategy
      ↓
Signal
      ↓
Execution Simulator
      ↓
Portfolio Simulator
      ↓
Performance Analyzer
```

Calculate:

```text
Total trades
Winning trades
Losing trades
Win rate
Average win
Average loss
Profit factor
Net profit
Maximum drawdown
Sharpe ratio
Sortino ratio
Average R/R
```

---

# 20. Avoid a major ML mistake: data leakage

This will be an excellent interview/assignment point.

Never do:

```text
2020 ─────────── 2025
       ↓
Backtest
       ↓
Tune strategy
       ↓
Backtest same data
       ↓
Claim 75%
```

Instead:

```text
Historical Data

├──────────────┬────────────┬──────────────┐
│              │            │              │
Training       Validation   Out-of-sample
               │            │
               │            │
Strategy       Tune         Final test
development
```

For example:

```text
2021-2023 → Development
2024      → Validation
2025      → Out-of-sample
2026      → Paper trading
```

---

# 21. Confidence scoring

Don't confuse:

```text
AI confidence
```

with:

```text
Probability of profit
```

For example:

```text
Signal score

TA              30%
Trend           20%
Volume          15%
Market regime   15%
Sentiment       10%
Risk             10%
```

Total:

```text
82 / 100
```

Call this:

> **Signal Score**

rather than saying:

> "82% chance BTC will go up."

That's a much safer and more technically defensible design.

---

# 22. Database design

You could use:

```text
PostgreSQL
```

with tables:

```text
users
portfolios
assets
market_data
indicators
strategies
signals
trades
orders
positions
paper_orders
backtest_runs
strategy_metrics
agent_decisions
risk_events
```

Example:

```text
signals

id
symbol
timeframe
strategy_id
signal
entry
stop_loss
take_profit
signal_score
created_at
```

---

# 23. Recommended technology stack

For your background and AI assignment, I'd use:

```text
Frontend
────────
React / Next.js

Backend
───────
Python
FastAPI

AI
──
Claude / OpenAI

Agents
──────
LangGraph

Trading
───────
CCXT

Market
──────
TradingView
CoinGecko
Exchange WebSockets

Database
────────
PostgreSQL

Cache
─────
Redis

Background Jobs
───────────────
Celery / Redis
or
Temporal

Vector DB
─────────
Optional
FAISS / pgvector

Monitoring
──────────
Prometheus
Grafana

Deployment
──────────
Docker
AWS / GCP / Azure
```

---

# 24. MCP can make this even better

Since you're learning MCP, this is a very good place to demonstrate it.

Create tools such as:

```text
get_price()
get_ohlcv()
get_orderbook()
get_portfolio()
get_open_positions()
calculate_indicators()
run_backtest()
get_strategy_metrics()
calculate_position_size()
create_paper_order()
get_paper_pnl()
```

Then:

```text
AI Agent
   │
   ▼
MCP
   │
   ├── Market Tool
   ├── TA Tool
   ├── Portfolio Tool
   ├── Backtest Tool
   ├── Risk Tool
   └── Paper Trading Tool
```

**Important:** don't expose `place_live_order()` directly to an autonomous LLM without a hard risk/approval layer.

---

# 25. Recommended agent workflow

This is the workflow I would actually implement for your POC:

```text
                EVERY 5 MINUTES
                       │
                       ▼
                Market Collector
                       │
                       ▼
                Feature Generator
                       │
                       ▼
                 TA Strategies
                       │
                       ▼
              Signal Candidates
                       │
                       ▼
               Strategy Filter
                       │
             Win rate >= 70%?
                       │
                 ┌─────┴─────┐
                 NO          YES
                 │             │
              IGNORE          ▼
                         AI Analysis
                              │
                              ▼
                        Market Context
                              │
                              ▼
                         Risk Engine
                              │
                       Risk acceptable?
                              │
                       ┌──────┴──────┐
                       NO             YES
                       │               │
                     REJECT            ▼
                                 Paper Trade
                                      │
                                      ▼
                                  Monitor
                                      │
                                      ▼
                                  Outcome
                                      │
                                      ▼
                              Performance DB
                                      │
                                      ▼
                              Strategy Metrics
```

---

# 26. Live mode

When everything passes:

```text
                   USER
                    │
             Select LIVE mode
                    │
                    ▼
              Safety checks
                    │
          ┌─────────┴─────────┐
          │                   │
       API valid          Risk limits
          │                   │
          └─────────┬─────────┘
                    ▼
               Trade proposal
                    │
                    ▼
              Human approval
                    │
                    ▼
                Exchange
                    │
                    ▼
                Order ID
                    │
                    ▼
              Order Monitor
```

For the assignment, I would make **human approval mandatory in the first version**.

Later you can demonstrate:

```text
Paper → Assisted Live → Controlled Autonomous
```

---

# 27. Security architecture

This is another important interview point.

Never put:

```text
BINANCE_SECRET_KEY
```

inside:

```text
prompt
LLM context
frontend
GitHub
database plaintext
```

Use:

```text
AWS Secrets Manager
       or
HashiCorp Vault
       or
Azure Key Vault
```

And exchange API keys should have:

```text
Trading permission
     YES

Withdrawal permission
     ❌ NO
```

The CCXT documentation also emphasizes keeping exchange secrets secure and notes that API permissions should be configured carefully. ([CCXT][5])

---

# 28. Suggested UI

Your dashboard could have:

```text
┌───────────────────────────────────────────────┐
│ AI CRYPTO TRADING ASSISTANT                   │
├───────────────────────────────────────────────┤
│ Mode: [ PAPER ▼ ]                             │
│                                               │
│ Portfolio: $10,000                            │
│ Today P&L: +$184                              │
│                                               │
│ ┌─────────────┐ ┌─────────────┐               │
│ │ BTC         │ │ ETH         │               │
│ │ BUY 🟢      │ │ HOLD 🟡     │               │
│ │ 81 score    │ │ 54 score    │               │
│ └─────────────┘ └─────────────┘               │
│                                               │
│ Active Strategies                             │
│ EMA+RSI       73.4%   ✅                      │
│ Breakout      72.1%   ✅                      │
│ MACD          64.3%   ❌                      │
│                                               │
│ Paper Trades                                  │
│ BTC/USDT     +$120                            │
│ SOL/USDT     +$64                             │
└───────────────────────────────────────────────┘
```

---

# 29. APIs/components for your assignment

| Requirement         | Recommended                        |
| ------------------- | ---------------------------------- |
| Charts              | TradingView                        |
| TradingView signals | TradingView Webhooks               |
| Market data         | Exchange APIs                      |
| Multiple exchanges  | CCXT                               |
| Crypto metadata     | CoinGecko                          |
| Historical candles  | Exchange/CoinGecko                 |
| Real-time data      | Exchange WebSocket                 |
| TA                  | Python                             |
| AI                  | Claude/OpenAI                      |
| Agent orchestration | LangGraph                          |
| Agent tools         | MCP                                |
| Backend             | FastAPI                            |
| Database            | PostgreSQL                         |
| Cache               | Redis                              |
| Paper trading       | Custom simulator                   |
| Exchange testing    | Binance Testnet / exchange sandbox |
| Frontend            | React/Next.js                      |
| Deployment          | Docker + cloud                     |
| Secrets             | Vault/Secrets Manager              |
| Monitoring          | Prometheus/Grafana                 |

CCXT is particularly useful here because it provides a unified interface across many exchange APIs rather than forcing you to implement every exchange separately. ([CCXT][4])

---

# 30. MVP I would build for your assignment

Don't try to build everything at once.

### Phase 1 — Market data

```text
Binance
   ↓
BTC/ETH/SOL
   ↓
OHLCV
   ↓
PostgreSQL
```

### Phase 2 — TA

Implement:

```text
RSI
EMA
MACD
Volume
ATR
Support/Resistance
```

### Phase 3 — Strategy

Build:

```text
EMA + RSI + MACD strategy
```

Backtest it.

### Phase 4 — Performance engine

Implement:

```text
Win rate
Profit factor
Drawdown
Sharpe
Trade history
```

### Phase 5 — TradingView

```text
TradingView
     ↓
Webhook
     ↓
FastAPI
     ↓
Signal Engine
```

### Phase 6 — AI agent

```text
Signal
  +
Market context
  +
Strategy statistics
  +
Risk
       ↓
    AI Agent
       ↓
Trade proposal
```

### Phase 7 — Paper trading

```text
Real market
     ↓
AI signal
     ↓
Paper order
     ↓
Virtual portfolio
     ↓
P&L
```

### Phase 8 — Testnet

Connect to Binance Testnet.

### Phase 9 — Controlled live

Only after all validation gates pass.

---

# 31. The final architecture I'd present in your assignment

```text
                         ┌───────────────┐
                         │  TradingView  │
                         │ Alerts/Webhook │
                         └───────┬───────┘
                                 │
                                 ▼
┌──────────────┐        ┌──────────────────┐
│ Exchange APIs│───────►│ Market Data Layer│
└──────────────┘        └────────┬─────────┘
                                 │
                         ┌───────▼────────┐
                         │ Feature / TA    │
                         │ RSI MACD EMA    │
                         │ ATR Volume etc. │
                         └───────┬─────────┘
                                 │
                         ┌───────▼────────┐
                         │ Strategy Engine │
                         └───────┬────────┘
                                 │
                         Win Rate >= 70%?
                            /           \
                          NO             YES
                          │               │
                       REJECT             ▼
                                  ┌──────────────┐
                                  │ AI Supervisor│
                                  └──────┬───────┘
                                         │
                          ┌──────────────┼─────────────┐
                          ▼              ▼             ▼
                       Market           TA            Risk
                       Agent          Agent          Agent
                          │              │             │
                          └──────────────┼─────────────┘
                                         ▼
                                  Trade Proposal
                                         │
                                         ▼
                                  HARD RISK ENGINE
                                         │
                              ┌──────────┴──────────┐
                              ▼                     ▼
                           PAPER                 LIVE
                              │                     │
                              ▼                     ▼
                       Virtual Orders          Exchange
                              │
                              ▼
                       Performance Engine
                              │
                 ┌────────────┼─────────────┐
                 ▼            ▼             ▼
              Win Rate      Drawdown      P&L
                 │
                 ▼
          Strategy Evaluation
```

### The key story for your assignment

You can explain it in one sentence:

> **"The system combines deterministic technical-analysis strategies with an AI multi-agent layer for market reasoning, a hard risk engine for trade validation, and separate backtest, paper, testnet, and controlled-live execution environments."**

That is a **much stronger GenAI/AI Engineer project** than simply building an LLM that says "BUY BTC." It demonstrates **agents + RAG/context + APIs + MCP + Python + quantitative analysis + backtesting + risk management + real-time systems + paper trading + production architecture**.

One important caveat: a claimed **70% TA success rate must be demonstrated on sufficiently large, out-of-sample/paper-trading data and should not be presented as a guarantee of future returns**. Crypto markets can change regimes, and historical performance can fail in live conditions.

[1]: https://www.binance.com/en-IN/support/faq/detail/ab78f9a1b8824cf0a106b4229c76496d?utm_source=chatgpt.com "How to Test My Functions on Binance Testnet? | Binance Support"
[2]: https://in.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/?utm_source=chatgpt.com "How to configure webhook alerts — TradingView India"
[3]: https://www.tradingview.com/support/solutions/43000595315-how-to-set-up-alerts/?utm_source=chatgpt.com "How to set up alerts — TradingView"
[4]: https://docs.ccxt.com/?utm_source=chatgpt.com "CCXT — API For Crypto Exchanges And Prediction Markets"
[5]: https://docs.ccxt.com/docs/manual?id=order-structure&utm_source=chatgpt.com "Manual | CCXT"
