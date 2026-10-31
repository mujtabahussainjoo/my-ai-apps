"""Travel tools: flight, hotel and rail discovery."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from nexapilot.agents.permissions import TRAVEL_SEARCH
from nexapilot.core.errors import ExternalServiceNotConfiguredError
from nexapilot.tools.base import Tool, ToolContext, ToolRisk, ToolSpec

TRAVEL_SECRET_REFERENCE = "travel:amadeus:api_key"
TRAVEL_SECRET_REFERENCE_SECRET = "travel:amadeus:api_secret"


class FlightSearchInput(BaseModel):
    origin: str = Field(min_length=3, max_length=10)
    destination: str = Field(min_length=3, max_length=10)
    departure_date: str = Field(min_length=8, max_length=20)
    adults: int = Field(default=1, ge=1, le=9)


class HotelSearchInput(BaseModel):
    city: str = Field(min_length=2, max_length=60)
    check_in: str = Field(min_length=8, max_length=20)
    check_out: str = Field(min_length=8, max_length=20)


class TrainSearchInput(BaseModel):
    origin: str = Field(min_length=2, max_length=60)
    destination: str = Field(min_length=2, max_length=60)
    departure_date: str = Field(min_length=8, max_length=20)


class TravelSearchOutput(BaseModel):
    provider: str = ""
    query: dict[str, Any] = Field(default_factory=dict)
    offers: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_at: str = ""
    limitations: str = ""


def _build_provider(ctx: ToolContext) -> Any:
    settings = ctx.container.settings
    provider = settings.travel_provider
    if not provider:
        raise ExternalServiceNotConfiguredError(
            "No travel provider is configured, so live availability cannot be checked.",
            setup_hint="Configure the Amadeus provider in Settings → Travel.",
        )
    from nexapilot.integrations.travel import build_travel_provider

    if provider == "amadeus":
        client_id = ctx.container.secrets.get(TRAVEL_SECRET_REFERENCE) or ""
        client_secret = ctx.container.secrets.get(TRAVEL_SECRET_REFERENCE_SECRET) or ""
        return build_travel_provider(
            provider,
            client_id=client_id,
            client_secret=client_secret,
            base_url=settings.travel_api_base_url,
        )
    return build_travel_provider(provider)


class SearchFlightsTool(Tool):
    spec = ToolSpec(
        name="search_flights",
        purpose="Search available flights and return price, timing and fare details.",
        input_model=FlightSearchInput,
        output_model=TravelSearchOutput,
        permissions=frozenset({TRAVEL_SEARCH}),
        side_effects=False,
        timeout_seconds=60.0,
        max_retries=1,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, FlightSearchInput)
        provider = _build_provider(ctx)
        offers = await provider.search_flights(
            args.origin, args.destination, args.departure_date, adults=args.adults
        )
        return TravelSearchOutput(
            provider=provider.id,
            query={
                "origin": args.origin,
                "destination": args.destination,
                "departure_date": args.departure_date,
                "adults": args.adults,
            },
            offers=[offer.to_dict() for offer in offers],
            retrieved_at=datetime.now(UTC).isoformat(),
            limitations="Prices and availability are as returned by the provider at retrieval time.",
        )


class SearchHotelsTool(Tool):
    spec = ToolSpec(
        name="search_hotels",
        purpose="Search available hotels and return nightly price and cancellation terms.",
        input_model=HotelSearchInput,
        output_model=TravelSearchOutput,
        permissions=frozenset({TRAVEL_SEARCH}),
        side_effects=False,
        timeout_seconds=60.0,
        max_retries=1,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, HotelSearchInput)
        provider = _build_provider(ctx)
        offers = await provider.search_hotels(args.city, args.check_in, args.check_out)
        return TravelSearchOutput(
            provider=provider.id,
            query={"city": args.city, "check_in": args.check_in, "check_out": args.check_out},
            offers=[offer.to_dict() for offer in offers],
            retrieved_at=datetime.now(UTC).isoformat(),
            limitations="Prices and availability are as returned by the provider at retrieval time.",
        )


class SearchTrainsTool(Tool):
    spec = ToolSpec(
        name="search_trains",
        purpose=(
            "Look up rail travel options. When no permitted rail booking API is available, "
            "returns the official booking guidance instead of inventing availability."
        ),
        input_model=TrainSearchInput,
        output_model=TravelSearchOutput,
        permissions=frozenset({TRAVEL_SEARCH}),
        side_effects=False,
        timeout_seconds=60.0,
        idempotent=True,
        audit=True,
        risk=ToolRisk.LOW,
    )

    async def run(self, args: BaseModel, ctx: ToolContext) -> BaseModel:
        assert isinstance(args, TrainSearchInput)
        provider = _build_provider(ctx)
        offers = await provider.search_trains(args.origin, args.destination, args.departure_date)
        return TravelSearchOutput(
            provider=provider.id,
            query={
                "origin": args.origin,
                "destination": args.destination,
                "departure_date": args.departure_date,
            },
            offers=[offer.to_dict() for offer in offers],
            retrieved_at=datetime.now(UTC).isoformat(),
            limitations=(
                "Rail inventory and booking are only available through the official operator "
                "portal; this assistant cannot complete rail bookings."
            ),
        )
