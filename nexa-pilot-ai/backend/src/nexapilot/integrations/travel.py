"""Travel providers.

Flights and hotels are discovered through the Amadeus Self-Service APIs, which
require an API key and secret (client-credentials OAuth).

Rail travel has no permitted public booking API that this application can call.
The rail provider therefore returns *official booking links and guidance* — it
never claims that a booking was made.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from nexapilot.core.errors import ExternalServiceNotConfiguredError
from nexapilot.core.logging import get_logger
from nexapilot.providers.http import classify_status, wrap_transport_error

log = get_logger(__name__)


@dataclass(frozen=True)
class FlightOffer:
    id: str
    provider: str
    origin: str
    destination: str
    departure_at: datetime | None
    arrival_at: datetime | None
    price: float
    currency: str = "USD"
    carrier: str = ""
    flight_number: str = ""
    seats_left: int | None = None
    refundable: bool = False
    baggage_allowance: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "origin": self.origin,
            "destination": self.destination,
            "departure_at": self.departure_at.isoformat() if self.departure_at else None,
            "arrival_at": self.arrival_at.isoformat() if self.arrival_at else None,
            "price": self.price,
            "currency": self.currency,
            "carrier": self.carrier,
            "flight_number": self.flight_number,
            "seats_left": self.seats_left,
            "refundable": self.refundable,
            "baggage_allowance": self.baggage_allowance,
        }


@dataclass(frozen=True)
class HotelOffer:
    id: str
    provider: str
    name: str
    city: str
    price_per_night: float
    currency: str = "USD"
    check_in: str = ""
    check_out: str = ""
    room_name: str = ""
    refundable: bool = False
    breakfast_included: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "name": self.name,
            "city": self.city,
            "price_per_night": self.price_per_night,
            "currency": self.currency,
            "check_in": self.check_in,
            "check_out": self.check_out,
            "room_name": self.room_name,
            "refundable": self.refundable,
            "breakfast_included": self.breakfast_included,
        }


@dataclass(frozen=True)
class TrainOption:
    id: str
    provider: str
    origin: str
    destination: str
    departure_at: datetime | None
    arrival_at: datetime | None
    price: float | None
    currency: str = "INR"
    class_name: str = ""
    availability: str = "unknown"
    booking_url: str = ""
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "origin": self.origin,
            "destination": self.destination,
            "departure_at": self.departure_at.isoformat() if self.departure_at else None,
            "arrival_at": self.arrival_at.isoformat() if self.arrival_at else None,
            "price": self.price,
            "currency": self.currency,
            "class_name": self.class_name,
            "availability": self.availability,
            "booking_url": self.booking_url,
            "note": self.note,
        }


class TravelProvider(abc.ABC):
    id: str = "travel"

    @abc.abstractmethod
    async def search_flights(
        self, origin: str, destination: str, departure_date: str, *, adults: int = 1
    ) -> list[FlightOffer]: ...

    @abc.abstractmethod
    async def search_hotels(self, city: str, check_in: str, check_out: str) -> list[HotelOffer]: ...

    @abc.abstractmethod
    async def search_trains(
        self, origin: str, destination: str, departure_date: str
    ) -> list[TrainOption]: ...


class AmadeusProvider(TravelProvider):
    """Amadeus Self-Service APIs (flights + hotels)."""

    id = "amadeus"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        base_url: str = "https://test.api.amadeus.com",
        timeout: float = 45.0,
        transport: Any = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport
        self._token: str | None = None
        self._token_expires_at: datetime | None = None

    async def _access_token(self) -> str:
        now = datetime.now(UTC)
        if self._token and self._token_expires_at and now < self._token_expires_at:
            return self._token
        if not self._client_id or not self._client_secret:
            raise ExternalServiceNotConfiguredError(
                "The travel provider needs an API key and secret.",
                setup_hint="Set the Amadeus API key and secret in Settings → Travel.",
            )
        url = f"{self._base_url}/v1/security/oauth2/token"
        data = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport, follow_redirects=False
        ) as client:
            try:
                response = await client.post(url, data=data)
            except httpx.HTTPError as exc:
                raise wrap_transport_error(exc, "Amadeus", self._timeout) from exc
            if response.status_code >= 400:
                raise classify_status(response.status_code, "Amadeus", response.text)
            payload = response.json()
        self._token = str(payload.get("access_token") or "")
        expires_in = int(payload.get("expires_in") or 1800)
        self._token_expires_at = now + timedelta(seconds=expires_in)
        return self._token

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        token = await self._access_token()
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport, follow_redirects=False
        ) as client:
            try:
                response = await client.get(
                    url, params=params, headers={"authorization": f"Bearer {token}"}
                )
            except httpx.HTTPError as exc:
                raise wrap_transport_error(exc, "Amadeus", self._timeout) from exc
            if response.status_code >= 400:
                raise classify_status(response.status_code, "Amadeus", response.text)
            payload: dict[str, Any] = response.json()
            return payload

    async def search_flights(
        self, origin: str, destination: str, departure_date: str, *, adults: int = 1
    ) -> list[FlightOffer]:
        payload = await self._get(
            "/v2/shopping/flight-offers",
            {
                "originLocationCode": origin.upper(),
                "destinationLocationCode": destination.upper(),
                "departureDate": departure_date,
                "adults": str(max(1, adults)),
                "currencyCode": "USD",
                "max": "20",
            },
        )
        offers: list[FlightOffer] = []
        for offer in payload.get("data") or []:
            price = (offer.get("price") or {}).get("grandTotal")
            itineraries = offer.get("itineraries") or []
            segments = (itineraries[0].get("segments") or []) if itineraries else []
            first = segments[0] if segments else {}
            last = segments[-1] if segments else {}
            carrier = ((first.get("carrierCode") or "") + " " + (first.get("number") or "")).strip()
            offers.append(
                FlightOffer(
                    id=str(offer.get("id") or ""),
                    provider=self.id,
                    origin=origin.upper(),
                    destination=destination.upper(),
                    departure_at=_parse_dt(first.get("departure")),
                    arrival_at=_parse_dt(last.get("arrival")),
                    price=float(price) if price is not None else 0.0,
                    currency=str((offer.get("price") or {}).get("currency") or "USD"),
                    carrier=carrier,
                    flight_number=carrier,
                    seats_left=first.get("numberOfBookableSeats"),
                    refundable=bool((offer.get("price") or {}).get("refundable")),
                    raw=offer,
                )
            )
        return offers

    async def search_hotels(self, city: str, check_in: str, check_out: str) -> list[HotelOffer]:
        payload = await self._get(
            "/v1/reference-data/locations/hotels/by-city",
            {"cityCode": city.upper(), "radius": "20", "radiusUnit": "KM"},
        )
        hotel_ids = [
            str(item.get("hotelId")) for item in payload.get("data") or [] if item.get("hotelId")
        ]
        if not hotel_ids:
            return []
        offers_payload = await self._get(
            "/v3/shopping/hotel-offers",
            {
                "hotelIds": ",".join(hotel_ids[:20]),
                "checkInDate": check_in,
                "checkOutDate": check_out,
                "adults": "1",
            },
        )
        offers: list[HotelOffer] = []
        for offer in offers_payload.get("data") or []:
            hotel = offer.get("hotel") or {}
            room = ((offer.get("rooms") or [{}])[0]) or {}
            price = ((room.get("rates") or [{}])[0] or {}).get("total")
            offers.append(
                HotelOffer(
                    id=str(offer.get("id") or ""),
                    provider=self.id,
                    name=str(hotel.get("name") or ""),
                    city=city.upper(),
                    price_per_night=float(price) if price is not None else 0.0,
                    currency=str(((room.get("rates") or [{}])[0] or {}).get("currency") or "USD"),
                    check_in=check_in,
                    check_out=check_out,
                    room_name=str(room.get("name") or ""),
                    refundable=bool(((room.get("rates") or [{}])[0] or {}).get("refundable")),
                    raw=offer,
                )
            )
        return offers

    async def search_trains(
        self, origin: str, destination: str, departure_date: str
    ) -> list[TrainOption]:
        """Amadeus does not cover rail. The caller gets the official guidance."""
        return [
            TrainOption(
                id="rail-guidance",
                provider="official-rail-portal",
                origin=origin,
                destination=destination,
                departure_at=None,
                arrival_at=None,
                price=None,
                availability="requires-official-booking",
                booking_url="https://www.indianrail.gov.in/enquiry/StaticPages/StaticEnquiry.jsp",
                note=(
                    "Rail inventory and booking are only available through the official Indian "
                    "Railways booking portal; no permitted public booking API is available here."
                ),
            )
        ]


class OfficialRailGuidanceProvider(TravelProvider):
    """Rail provider that only returns official booking guidance."""

    id = "official-rail-portal"

    async def search_flights(
        self, origin: str, destination: str, departure_date: str, *, adults: int = 1
    ) -> list[FlightOffer]:
        raise ExternalServiceNotConfiguredError(
            "Rail guidance provider does not serve flight offers.",
            setup_hint="Select the Amadeus provider for flights and hotels.",
        )

    async def search_hotels(self, city: str, check_in: str, check_out: str) -> list[HotelOffer]:
        raise ExternalServiceNotConfiguredError(
            "Rail guidance provider does not serve hotel offers.",
            setup_hint="Select the Amadeus provider for flights and hotels.",
        )

    async def search_trains(
        self, origin: str, destination: str, departure_date: str
    ) -> list[TrainOption]:
        return [
            TrainOption(
                id="rail-guidance",
                provider=self.id,
                origin=origin,
                destination=destination,
                departure_at=None,
                arrival_at=None,
                price=None,
                availability="requires-official-booking",
                booking_url="https://www.indianrail.gov.in/enquiry/StaticPages/StaticEnquiry.jsp",
                note=(
                    "Use the official Indian Railways portal to check live availability and "
                    "complete the booking; this assistant cannot book rail tickets."
                ),
            )
        ]


def build_travel_provider(
    provider: str,
    *,
    client_id: str = "",
    client_secret: str = "",
    base_url: str = "https://test.api.amadeus.com",
    timeout: float = 45.0,
    transport: Any = None,
) -> TravelProvider:
    if provider == "amadeus":
        return AmadeusProvider(
            client_id=client_id,
            client_secret=client_secret,
            base_url=base_url,
            timeout=timeout,
            transport=transport,
        )
    if provider == "rail-guidance":
        return OfficialRailGuidanceProvider()
    raise ExternalServiceNotConfiguredError(
        "No travel provider is configured, so live availability cannot be checked.",
        setup_hint="Configure the Amadeus provider in Settings → Travel.",
    )


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
