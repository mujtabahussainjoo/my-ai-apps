"""Finance service: quotes, portfolio views, watchlists and orders."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from nexapilot.core.errors import (
    ExternalServiceNotConfiguredError,
    IntegrationError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from nexapilot.db.models import AuditLog, Order, Portfolio, Position, WatchlistItem
from nexapilot.integrations.market_data import Quote, build_quote_provider
from nexapilot.tools.base import ToolContext


def _quote_provider(ctx: ToolContext) -> Any:
    provider = ctx.container.settings.finance_provider
    if not provider:
        raise ExternalServiceNotConfiguredError(
            "No market data provider is configured, so live quotes are unavailable.",
            setup_hint="Set the market data provider in Settings → Finance (stooq or yahoo).",
        )
    return build_quote_provider(provider)


async def get_quote(ctx: ToolContext, symbol: str) -> Quote:
    quote: Quote = await _quote_provider(ctx).quote(symbol)
    return quote


def get_or_create_portfolio(ctx: ToolContext, *, name: str = "Main") -> Portfolio:
    portfolio = ctx.session.scalars(select(Portfolio).where(Portfolio.name == name)).first()
    if portfolio is None:
        portfolio = Portfolio(name=name, currency="USD", is_paper=True)
        ctx.session.add(portfolio)
        ctx.session.flush()
    return portfolio


async def portfolio_summary(ctx: ToolContext, portfolio_id: str = "") -> dict[str, Any]:
    """Value the portfolio using the latest available quotes."""
    if portfolio_id:
        portfolio = ctx.session.get(Portfolio, portfolio_id)
        if portfolio is None:
            raise NotFoundError(f"Portfolio '{portfolio_id}' not found")
    else:
        portfolio = get_or_create_portfolio(ctx)

    positions = list(
        ctx.session.scalars(select(Position).where(Position.portfolio_id == portfolio.id))
    )
    holdings: list[dict[str, Any]] = []
    total_value = 0.0
    total_cost = 0.0
    unpriced: list[str] = []

    for position in positions:
        cost = position.average_cost * position.quantity
        total_cost += cost
        try:
            quote = await get_quote(ctx, position.symbol)
        except (ExternalServiceNotConfiguredError, IntegrationError):
            unpriced.append(position.symbol)
            holdings.append(
                {
                    "symbol": position.symbol,
                    "quantity": position.quantity,
                    "average_cost": position.average_cost,
                    "price": None,
                    "value": None,
                    "unrealised_pnl": None,
                    "quote_source": None,
                    "quote_timestamp": None,
                }
            )
            continue
        value = quote.price * position.quantity
        total_value += value
        holdings.append(
            {
                "symbol": position.symbol,
                "asset_type": position.asset_type,
                "quantity": position.quantity,
                "average_cost": position.average_cost,
                "price": quote.price,
                "currency": quote.currency,
                "value": value,
                "unrealised_pnl": value - cost,
                "unrealised_pnl_pct": ((value - cost) / cost * 100) if cost else None,
                "quote_source": quote.source,
                "quote_timestamp": quote.as_of.isoformat() if quote.as_of else None,
                "is_delayed": quote.is_delayed,
                "delay_note": quote.delay_note,
            }
        )

    return {
        "portfolio_id": portfolio.id,
        "portfolio_name": portfolio.name,
        "currency": portfolio.currency,
        "is_paper": portfolio.is_paper,
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_value - total_cost, 2),
        "total_pnl_pct": round((total_value - total_cost) / total_cost * 100, 2)
        if total_cost
        else None,
        "holdings": holdings,
        "unpriced_symbols": unpriced,
        "note": (
            "Values use the latest available quote at retrieval time and may be delayed. "
            "They are not investment advice."
        ),
    }


async def place_order(
    ctx: ToolContext,
    *,
    symbol: str,
    side: str,
    quantity: float,
    portfolio_id: str = "",
    order_type: str = "market",
    limit_price: float | None = None,
    live: bool = False,
) -> dict[str, Any]:
    """Place an order. Live orders require an explicitly configured broker."""
    settings = ctx.container.settings
    if side not in ("buy", "sell"):
        raise ValidationError("side must be 'buy' or 'sell'")
    if quantity <= 0:
        raise ValidationError("quantity must be greater than zero")
    if quantity > settings.finance_max_order_quantity:
        raise PermissionDeniedError(
            f"Order quantity {quantity} exceeds the configured limit of "
            f"{settings.finance_max_order_quantity}",
            details={"limit": settings.finance_max_order_quantity},
        )

    portfolio = (
        ctx.session.get(Portfolio, portfolio_id) if portfolio_id else get_or_create_portfolio(ctx)
    )
    if portfolio is None:
        raise NotFoundError(f"Portfolio '{portfolio_id}' not found")

    quote = await get_quote(ctx, symbol)
    reference_price = quote.price if order_type == "market" else (limit_price or quote.price)
    notional = reference_price * quantity
    if notional > settings.finance_max_order_value:
        raise PermissionDeniedError(
            f"Order value {notional:.2f} {quote.currency} exceeds the configured limit of "
            f"{settings.finance_max_order_value:.2f}",
            details={"limit": settings.finance_max_order_value, "notional": notional},
        )

    status = "filled"
    filled_price: float | None = reference_price
    provider_reference = ""
    source = "paper"

    if live:
        broker = _broker_client(ctx)
        broker_order = await broker.place_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            limit_price=limit_price,
        )
        status = broker_order.status
        filled_price = broker_order.filled_price
        provider_reference = broker_order.id
        source = "live"
    else:
        filled_price = reference_price

    order = Order(
        portfolio_id=portfolio.id,
        symbol=symbol.upper(),
        side=side,
        order_type=order_type,
        quantity=quantity,
        limit_price=limit_price,
        status=status,
        filled_price=filled_price,
        market_price=quote.price,
        market_timestamp=quote.as_of,
        source=source,
        provider_reference=provider_reference,
        note=f"{side} {quantity} {symbol.upper()} at {reference_price:.4f} {quote.currency}",
    )
    ctx.session.add(order)
    ctx.session.flush()

    if source == "paper":
        _apply_paper_fill(ctx, portfolio, symbol.upper(), side, quantity, filled_price or 0.0)

    ctx.session.add(
        AuditLog(
            actor="agent",
            action="finance.order_placed",
            target=symbol.upper(),
            status="ok",
            details={
                "side": side,
                "quantity": quantity,
                "order_type": order_type,
                "source": source,
                "status": status,
                "price": filled_price,
                "currency": quote.currency,
            },
        )
    )
    ctx.session.flush()
    return {
        "order_id": order.id,
        "symbol": order.symbol,
        "side": side,
        "quantity": quantity,
        "order_type": order_type,
        "status": status,
        "filled_price": filled_price,
        "currency": quote.currency,
        "source": source,
        "provider_reference": provider_reference,
        "quote_source": quote.source,
        "quote_timestamp": quote.as_of.isoformat() if quote.as_of else None,
        "is_delayed": quote.is_delayed,
    }


def _apply_paper_fill(
    ctx: ToolContext,
    portfolio: Portfolio,
    symbol: str,
    side: str,
    quantity: float,
    price: float,
) -> None:
    position = ctx.session.scalars(
        select(Position).where(Position.portfolio_id == portfolio.id, Position.symbol == symbol)
    ).first()
    if position is None:
        position = Position(
            portfolio_id=portfolio.id, symbol=symbol, quantity=0.0, average_cost=0.0
        )
        ctx.session.add(position)
    if side == "buy":
        total_cost = position.average_cost * position.quantity + price * quantity
        total_quantity = position.quantity + quantity
        position.quantity = total_quantity
        position.average_cost = total_cost / total_quantity if total_quantity else 0.0
    else:
        position.quantity -= quantity
        if position.quantity <= 0:
            position.quantity = 0.0
            position.average_cost = 0.0
    ctx.session.flush()


def _broker_client(ctx: ToolContext) -> Any:
    from nexapilot.integrations.broker import RestBrokerClient

    settings = ctx.container.settings
    if not settings.finance_broker_base_url:
        raise ExternalServiceNotConfiguredError(
            "No live broker is configured, so live orders are not available.",
            setup_hint=(
                "Use paper trading, or configure a broker API in Settings → Finance "
                "to enable live orders."
            ),
        )
    api_key = ""
    if settings.finance_broker_api_key_ref:
        api_key = ctx.container.secrets.get(settings.finance_broker_api_key_ref) or ""
    return RestBrokerClient(base_url=settings.finance_broker_base_url, api_key=api_key)


def list_orders(ctx: ToolContext, portfolio_id: str = "", limit: int = 50) -> list[dict[str, Any]]:
    stmt = select(Order).order_by(Order.created_at.desc()).limit(limit)
    if portfolio_id:
        stmt = stmt.where(Order.portfolio_id == portfolio_id)
    return [
        {
            "id": order.id,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "order_type": order.order_type,
            "status": order.status,
            "filled_price": order.filled_price,
            "market_price": order.market_price,
            "market_timestamp": order.market_timestamp.isoformat()
            if order.market_timestamp
            else None,
            "source": order.source,
            "provider_reference": order.provider_reference,
            "created_at": order.created_at.isoformat(),
        }
        for order in ctx.session.scalars(stmt)
    ]


def watchlist(ctx: ToolContext) -> list[dict[str, Any]]:
    items = ctx.session.scalars(select(WatchlistItem).order_by(WatchlistItem.symbol)).all()
    return [
        {
            "symbol": item.symbol,
            "asset_type": item.asset_type,
            "note": item.note,
            "created_at": item.created_at.isoformat(),
        }
        for item in items
    ]


def add_to_watchlist(ctx: ToolContext, symbol: str, *, note: str = "") -> dict[str, Any]:
    normalized = symbol.upper()
    existing = ctx.session.scalars(
        select(WatchlistItem).where(WatchlistItem.symbol == normalized)
    ).first()
    if existing is None:
        ctx.session.add(WatchlistItem(symbol=normalized, note=note))
        ctx.session.flush()
    return {"symbol": normalized, "added": True}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
