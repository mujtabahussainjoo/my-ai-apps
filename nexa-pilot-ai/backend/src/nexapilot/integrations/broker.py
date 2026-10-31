"""Broker client for live orders.

A generic REST broker adapter. It is only usable when the user configures a
broker base URL and API key; without them, live orders are refused and only
paper trading is available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from nexapilot.core.errors import ExternalServiceNotConfiguredError, IntegrationError
from nexapilot.providers.http import classify_status, wrap_transport_error


@dataclass(frozen=True)
class BrokerOrder:
    id: str
    symbol: str
    side: str
    quantity: float
    order_type: str = "market"
    status: str = "accepted"
    filled_price: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "order_type": self.order_type,
            "status": self.status,
            "filled_price": self.filled_price,
        }


class RestBrokerClient:
    """Posts orders to a configured broker REST API."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: float = 30.0,
        transport: Any = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        return headers

    async def place_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        limit_price: float | None = None,
    ) -> BrokerOrder:
        if not self._base_url:
            raise ExternalServiceNotConfiguredError(
                "No live broker is configured, so live orders are not available.",
                setup_hint=(
                    "Use paper trading, or configure a broker API in Settings → Finance "
                    "to enable live orders."
                ),
            )
        payload: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "order_type": order_type,
        }
        if limit_price is not None:
            payload["limit_price"] = limit_price
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport, follow_redirects=False
        ) as client:
            try:
                response = await client.post(
                    f"{self._base_url}/orders", json=payload, headers=self._headers()
                )
            except httpx.HTTPError as exc:
                raise wrap_transport_error(exc, "broker", self._timeout) from exc
            if response.status_code >= 400:
                raise classify_status(response.status_code, "broker", response.text)
            data = response.json()
        return _parse_order(data)

    async def get_order(self, order_id: str) -> BrokerOrder:
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport, follow_redirects=False
        ) as client:
            try:
                response = await client.get(
                    f"{self._base_url}/orders/{order_id}", headers=self._headers()
                )
            except httpx.HTTPError as exc:
                raise wrap_transport_error(exc, "broker", self._timeout) from exc
            if response.status_code >= 400:
                raise classify_status(response.status_code, "broker", response.text)
            data = response.json()
        return _parse_order(data)


def _parse_order(data: dict[str, Any]) -> BrokerOrder:
    if not isinstance(data, dict) or not data.get("id"):
        raise IntegrationError("The broker did not return an order confirmation")
    return BrokerOrder(
        id=str(data.get("id")),
        symbol=str(data.get("symbol") or ""),
        side=str(data.get("side") or ""),
        quantity=float(data.get("quantity") or 0),
        order_type=str(data.get("order_type") or "market"),
        status=str(data.get("status") or "accepted"),
        filled_price=(
            float(data["filled_price"]) if data.get("filled_price") is not None else None
        ),
        raw=data,
    )
