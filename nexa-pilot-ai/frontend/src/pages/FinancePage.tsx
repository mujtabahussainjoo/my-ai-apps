import { useCallback, useEffect, useState } from "react";

import { ApprovalCard } from "../components/ApprovalCard";
import { Callout, Card, EmptyState, Field, PageHeader } from "../components/ui";
import { useToolAction } from "../hooks/useToolAction";
import { api } from "../lib/api";
import { money, shortDate, titleCase } from "../lib/format";
import { describeError, useApp } from "../state/store";

interface Quote {
  symbol: string;
  price: number;
  currency: string;
  source: string;
  retrieved_at: string;
  market_status: string;
  is_delayed: boolean;
  delay_note: string;
}

export function FinancePage() {
  const { settings, notify, refresh } = useApp();
  const { busy, pending, result, run, approve } = useToolAction();
  const [portfolio, setPortfolio] = useState<Record<string, unknown> | null>(null);
  const [watchlist, setWatchlist] = useState<Array<Record<string, unknown>>>([]);
  const [orders, setOrders] = useState<Array<Record<string, unknown>>>([]);
  const [symbol, setSymbol] = useState("");
  const [order, setOrder] = useState({
    symbol: "",
    side: "buy",
    quantity: "1",
    order_type: "market",
    limit_price: "",
    live: false,
  });

  const load = useCallback(async () => {
    try {
      const [nextPortfolio, nextWatchlist, nextOrders] = await Promise.all([
        api.portfolio(),
        api.watchlist(),
        api.orders(),
      ]);
      setPortfolio(nextPortfolio);
      setWatchlist(nextWatchlist);
      setOrders(nextOrders);
    } catch (error) {
      const info = describeError(error);
      notify("error", info.message, info.hint);
    }
  }, [notify]);

  useEffect(() => {
    void load();
  }, [load]);

  const quote = ((): Quote | null => {
    if (result?.status !== "completed") return null;
    const output = result.output as unknown as Quote;
    return output.symbol ? output : null;
  })();

  const holdings = (portfolio?.holdings as Array<Record<string, unknown>> | undefined) ?? [];
  const providerConfigured = settings?.integrations.finance.configured ?? false;

  const placeOrder = async () => {
    const response = await run("place_order", {
      symbol: order.symbol.toUpperCase(),
      side: order.side,
      quantity: Number(order.quantity),
      order_type: order.order_type,
      limit_price: order.limit_price ? Number(order.limit_price) : null,
      live: order.live,
    });
    if (response?.status === "completed") {
      notify("success", `${order.live ? "Live" : "Paper"} order submitted.`);
      await Promise.all([load(), refresh()]);
    }
  };

  return (
    <div className="page">
      <PageHeader
        title="Finance"
        subtitle="Research-first market data with source and timestamp, paper trading by default."
        actions={
          <button type="button" className="btn ghost" onClick={() => void load()}>
            Refresh
          </button>
        }
      />

      {!providerConfigured ? (
        <Callout kind="warn" title="No market data provider configured">
          Set Stooq or Yahoo in Settings → Integrations. Quotes show their source and delay; stale
          data is never labelled live.
        </Callout>
      ) : null}

      <div className="grid stats">
        <Card title="Portfolio value">
          <p className="stat">{money(portfolio?.total_value as number, String(portfolio?.currency ?? "USD"))}</p>
          <p className={`muted small ${Number(portfolio?.total_pnl ?? 0) < 0 ? "error-text" : "ok-text"}`}>
            {money(portfolio?.total_pnl as number, String(portfolio?.currency ?? "USD"))} unrealised
          </p>
        </Card>
        <Card title="Positions">
          <p className="stat">{holdings.length}</p>
          <p className="muted small">
            {(portfolio?.unpriced_symbols as string[] | undefined)?.length
              ? `${(portfolio?.unpriced_symbols as string[]).length} unpriced`
              : "All positions priced"}
          </p>
        </Card>
        <Card title="Watchlist">
          <p className="stat">{watchlist.length}</p>
          <p className="muted small">Tracked symbols</p>
        </Card>
        <Card title="Orders">
          <p className="stat">{orders.length}</p>
          <p className="muted small">Paper and live history</p>
        </Card>
      </div>

      <div className="grid two">
        <Card title="Quote lookup">
          <div className="row">
            <input
              value={symbol}
              onChange={(event) => setSymbol(event.target.value.toUpperCase())}
              placeholder="AAPL, VOO, BTC-USD…"
              aria-label="Symbol"
            />
            <button
              type="button"
              className="btn primary"
              disabled={busy || !symbol}
              onClick={() => void run("quote_symbol", { symbol })}
            >
              Quote
            </button>
            <button
              type="button"
              className="btn ghost"
              disabled={busy || !symbol}
              onClick={() => void run("watchlist", { symbol }).then(() => load())}
            >
              Watch
            </button>
          </div>
          {quote ? (
            <div className="quote">
              <strong>{quote.symbol}</strong>
              <span className="stat">{money(quote.price, quote.currency)}</span>
              <span className="muted small">
                {quote.source} · {shortDate(quote.retrieved_at)} · {quote.market_status}
                {quote.is_delayed ? " · delayed" : ""}
              </span>
              {quote.delay_note ? <span className="muted small">{quote.delay_note}</span> : null}
            </div>
          ) : null}
        </Card>

        <Card title="Order ticket">
          <div className="grid two">
            <Field label="Symbol">
              <input
                value={order.symbol}
                onChange={(e) => setOrder({ ...order, symbol: e.target.value.toUpperCase() })}
              />
            </Field>
            <Field label="Side">
              <select value={order.side} onChange={(e) => setOrder({ ...order, side: e.target.value })}>
                <option value="buy">Buy</option>
                <option value="sell">Sell</option>
              </select>
            </Field>
            <Field label="Quantity">
              <input
                type="number"
                min={0}
                step="any"
                value={order.quantity}
                onChange={(e) => setOrder({ ...order, quantity: e.target.value })}
              />
            </Field>
            <Field label="Order type">
              <select
                value={order.order_type}
                onChange={(e) => setOrder({ ...order, order_type: e.target.value })}
              >
                <option value="market">Market</option>
                <option value="limit">Limit</option>
              </select>
            </Field>
          </div>
          {order.order_type === "limit" ? (
            <Field label="Limit price">
              <input
                type="number"
                min={0}
                step="any"
                value={order.limit_price}
                onChange={(e) => setOrder({ ...order, limit_price: e.target.value })}
              />
            </Field>
          ) : null}
          <label className="checkbox">
            <input
              type="checkbox"
              checked={order.live}
              onChange={(e) => setOrder({ ...order, live: e.target.checked })}
            />
            <span>Live order (uses the configured broker; otherwise paper only)</span>
          </label>
          <p className="muted small">
            Limits: max {money(settings?.limits.finance_max_order_value ?? 0)} and{" "}
            {settings?.limits.finance_max_order_quantity ?? 0} units per order.
          </p>
          <div className="row end">
            <button
              type="button"
              className={`btn ${order.live ? "danger" : "primary"}`}
              disabled={busy || !order.symbol || !order.quantity}
              onClick={() => void placeOrder()}
            >
              {order.live ? "Request live order" : "Request paper order"}
            </button>
          </div>
        </Card>
      </div>

      {pending ? (
        <ApprovalCard approval={pending.approval} busy={busy} onDecide={(ok) => void approve(ok)} />
      ) : null}

      <div className="grid two">
        <Card title="Holdings">
          {holdings.length ? (
            <table className="table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Quantity</th>
                  <th>Value</th>
                  <th>P/L</th>
                </tr>
              </thead>
              <tbody>
                {holdings.map((holding, index) => (
                  <tr key={`${holding.symbol ?? index}`}>
                    <td>{String(holding.symbol ?? "—")}</td>
                    <td>{String(holding.quantity ?? "—")}</td>
                    <td>{money(holding.market_value as number, String(portfolio?.currency ?? "USD"))}</td>
                    <td className={Number(holding.unrealised_pnl ?? 0) < 0 ? "error-text" : "ok-text"}>
                      {money(holding.unrealised_pnl as number, String(portfolio?.currency ?? "USD"))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState title="No positions">Add holdings or paper orders to see analysis.</EmptyState>
          )}
        </Card>

        <Card title="Recent orders">
          {orders.length ? (
            <ul className="list compact">
              {orders.slice(0, 8).map((item, index) => (
                <li key={`${item.id ?? index}`}>
                  <div>
                    <strong>
                      {String(item.side ?? "").toUpperCase()} {String(item.symbol ?? "")}
                    </strong>
                    <div className="muted small">
                      {String(item.quantity ?? "")} @ {item.filled_price ? money(item.filled_price as number) : "—"} ·{" "}
                      {titleCase(String(item.status ?? ""))} · {String(item.source ?? "paper")}
                    </div>
                  </div>
                  <span className="muted small">{shortDate(item.created_at as string)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No orders yet">Paper orders are recorded with their source.</EmptyState>
          )}
        </Card>
      </div>

      {watchlist.length ? (
        <Card title="Watchlist">
          <div className="row wrap">
            {watchlist.map((item, index) => (
              <span key={`${item.symbol ?? index}`} className="chip static">
                {String(item.symbol ?? "")}
              </span>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  );
}
