"""Finance tools: quotes, portfolio views, watchlist and orders."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from nexapilot.agents.permissions import FINANCE_READ, FINANCE_TRADE
from nexapilot.tools.base import Tool, ToolContext, ToolRisk, ToolSpec


class QuoteInput(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)


class QuoteOutput(BaseModel):
    symbol: str
    price: float
    currency: str = "USD"
    source: str = ""
    as_of: str | None = None
    retrieved_at: str = ""
    market_status: str = "unknown"
    is_delayed: bool = True
    delay_note: str = ""


class PortfolioInput(BaseModel):
    portfolio_id: str = Field(default="", max_length=64)


class PortfolioOutput(BaseModel):
    portfolio_id: str = ""
    portfolio_name: str = ""
    currency: str = "USD"
    total_value: float = 0.0
    total_cost: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float | None = None
    holdings: list[dict[str, Any]] = Field(default_factory=list)
    unpriced_symbols: list[str] = Field(default_factory=list)
    note: str = ""


class WatchlistInput(BaseModel):
    symbol: str = Field(default="", max_length=40)


class WatchlistOutput(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    count: int = 0


class PlaceOrderInput(BaseModel):
    symbol: str = Field(min_length=1, max_length=40)
    side: str = Field(min_length=3, max_length=4)
    quantity: float = Field(gt=0)
    order_type: str = Field(default="market", max_length=16)
    limit_price: float | None = None
    portfolio_id: str = Field(default="", max_length=64)
    live: bool = False


class PlaceOrderOutput(BaseModel):
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    status: str = ""
    filled_price: float | None = None
    currency: str = "USD"
    source: str = "paper"
    provider_reference: str = ""
    quote_source: str = ""
    quote_timestamp: str | None = None
    is_delayed: bool = True


class QuoteSymbolTool(Tool):
    spec = ToolSpec(
        name="quote_symbol",
        purpose=(
            "Get the latest available price for a stock, ETF, mutual fund or crypto asset, "
            "with the source and timestamp of the quote."
        ),
        input_model=QuoteInput,
        output_model=QuoteOutput,
        permissions=frozenset({FINANCE_READ}),
        side_effects=False,
        timeout_seconds=30.0,
        max_retries=1,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, QuoteInput)
        from nexapilot.services.finance_service import get_quote

        quote = await get_quote(ctx, args.symbol)
        return QuoteOutput(
            symbol=quote.symbol,
            price=quote.price,
            currency=quote.currency,
            source=quote.source,
            as_of=quote.as_of.isoformat() if quote.as_of else None,
            retrieved_at=quote.retrieved_at.isoformat(),
            market_status=quote.market_status,
            is_delayed=quote.is_delayed,
            delay_note=quote.delay_note,
        )


class PortfolioSummaryTool(Tool):
    spec = ToolSpec(
        name="portfolio_summary",
        purpose="Summarise portfolio positions, current value and unrealised profit or loss.",
        input_model=PortfolioInput,
        output_model=PortfolioOutput,
        permissions=frozenset({FINANCE_READ}),
        side_effects=False,
        timeout_seconds=60.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, PortfolioInput)
        from nexapilot.services.finance_service import portfolio_summary

        summary = await portfolio_summary(ctx, args.portfolio_id)
        return PortfolioOutput(**summary)


class WatchlistTool(Tool):
    spec = ToolSpec(
        name="watchlist",
        purpose="List or add items to the watchlist.",
        input_model=WatchlistInput,
        output_model=WatchlistOutput,
        permissions=frozenset({FINANCE_READ}),
        side_effects=False,
        timeout_seconds=30.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, WatchlistInput)
        from nexapilot.services.finance_service import add_to_watchlist, watchlist

        if args.symbol:
            add_to_watchlist(ctx, args.symbol)
        items = watchlist(ctx)
        return WatchlistOutput(items=items, count=len(items))


class PlaceOrderTool(Tool):
    spec = ToolSpec(
        name="place_order",
        purpose=(
            "Place a paper or live order. Requires an explicit approval for this specific "
            "order before it is submitted."
        ),
        input_model=PlaceOrderInput,
        output_model=PlaceOrderOutput,
        permissions=frozenset({FINANCE_READ, FINANCE_TRADE}),
        side_effects=True,
        timeout_seconds=60.0,
        max_retries=0,
        idempotent=False,
        audit=True,
        requires_approval=True,
        approval_action="finance.place_order",
        risk=ToolRisk.HIGH,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, PlaceOrderInput)
        from nexapilot.services.finance_service import place_order

        result = await place_order(
            ctx,
            symbol=args.symbol,
            side=args.side.lower(),
            quantity=args.quantity,
            portfolio_id=args.portfolio_id,
            order_type=args.order_type,
            limit_price=args.limit_price,
            live=args.live,
        )
        return PlaceOrderOutput(**result)
