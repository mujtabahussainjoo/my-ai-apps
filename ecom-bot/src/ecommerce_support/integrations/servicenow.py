"""ServiceNow incident adapter via the Table API (INT-004, FR-044/FR-051).

Config-driven and framework-free; tests use ``httpx.MockTransport``. Mirrors the Jira adapter's
confirmed-only contract: a ticket is reported created only from a confirmed 2xx response containing
a ``sys_id``; transport errors or non-2xx responses raise :class:`TicketCreationError`.
"""

from __future__ import annotations

import httpx

from ecommerce_support.core.config import IntegrationsConfig
from ecommerce_support.core.exceptions import (
    ConfigurationError,
    TicketCreationError,
    TicketingError,
)
from ecommerce_support.guardrails.redaction import redact_text
from ecommerce_support.integrations.ticketing import (
    TicketingAdapter,
    build_ticket_description,
)
from ecommerce_support.schemas import ExternalTicket, TicketRequest
from ecommerce_support.schemas.enums import TicketProvider, TicketStatus

_URGENCY = {"low": "3", "medium": "2", "high": "1", "urgent": "1"}

_STATE_MAP = {
    "1": TicketStatus.CREATED,
    "2": TicketStatus.IN_PROGRESS,
    "3": TicketStatus.IN_PROGRESS,
    "6": TicketStatus.RESOLVED,
    "7": TicketStatus.CLOSED,
    "8": TicketStatus.CLOSED,
}


def _text(value: str, redact: bool) -> str:
    return redact_text(value) if redact else value


def build_servicenow_payload(request: TicketRequest, *, redact: bool = True) -> dict[str, object]:
    """Build a ServiceNow incident payload with a redacted description (FR-050/FR-051)."""
    return {
        "short_description": _text(request.summary, redact),
        "description": build_ticket_description(request, redact=redact),
        "urgency": _URGENCY.get(request.priority.value, "2"),
        "category": "inquiry",
        "contact_type": "self-service",
    }


class ServiceNowTicketingAdapter(TicketingAdapter):
    """Creates ServiceNow incidents over the Table API (tests inject ``httpx.MockTransport``)."""

    provider = TicketProvider.SERVICENOW

    def __init__(
        self,
        *,
        instance: str,
        username: str,
        password: str,
        table: str = "incident",
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
        redact: bool = True,
    ) -> None:
        base_url = instance.rstrip("/") if instance.startswith("http") else f"https://{instance}"
        self._base_url = base_url
        self._table = table
        self._redact = redact
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._auth = (username, password)

    @classmethod
    def from_config(
        cls,
        config: IntegrationsConfig,
        *,
        client: httpx.AsyncClient | None = None,
        redact: bool = True,
    ) -> ServiceNowTicketingAdapter:
        """Build from validated config; fail loudly when required values are missing."""
        instance = config.servicenow_instance
        username = config.servicenow_username
        password = config.servicenow_password
        missing = [
            name
            for name, value in (
                ("servicenow_instance", instance),
                ("servicenow_username", username),
                ("servicenow_password", password),
            )
            if not value
        ]
        if missing:
            raise ConfigurationError(
                "ServiceNow ticketing is not fully configured.", details={"missing": missing}
            )
        assert instance and username and password  # narrowed above
        return cls(
            instance=instance,
            username=username,
            password=password,
            table=config.servicenow_table or "incident",
            client=client,
            redact=redact,
        )

    async def create_ticket(self, request: TicketRequest) -> ExternalTicket:
        payload = build_servicenow_payload(request, redact=self._redact)
        try:
            response = await self._client.post(
                f"/api/now/table/{self._table}",
                json=payload,
                headers={"Accept": "application/json"},
                auth=self._auth,
            )
        except httpx.HTTPError as exc:
            raise TicketCreationError(
                "ServiceNow did not confirm ticket creation.",
                details={"provider": self.provider.value, "reason": type(exc).__name__},
            ) from exc
        if response.status_code not in (200, 201):
            raise TicketCreationError(
                "ServiceNow did not confirm ticket creation.",
                details={"provider": self.provider.value, "status_code": response.status_code},
            )
        result = response.json().get("result") or {}
        sys_id = result.get("sys_id")
        if not sys_id:
            raise TicketCreationError(
                "ServiceNow response did not include a ticket id.",
                details={"provider": self.provider.value},
            )
        return ExternalTicket(
            provider=self.provider,
            external_id=sys_id,
            status=TicketStatus.CREATED,
            url=f"{self._base_url}/nav_to.do?uri={self._table}.do?sys_id={sys_id}",
            summary=request.summary,
        )

    async def get_status(self, external_id: str) -> ExternalTicket | None:
        try:
            response = await self._client.get(
                f"/api/now/table/{self._table}/{external_id}",
                params={"sysparm_fields": "number,state,short_description"},
                headers={"Accept": "application/json"},
                auth=self._auth,
            )
        except httpx.HTTPError as exc:
            raise TicketingError(
                "Could not reach ServiceNow to read ticket status.",
                details={"provider": self.provider.value, "reason": type(exc).__name__},
            ) from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise TicketingError(
                "ServiceNow returned an unexpected status.",
                details={"provider": self.provider.value, "status_code": response.status_code},
            )
        result = response.json().get("result") or {}
        state = str(result.get("state", ""))
        return ExternalTicket(
            provider=self.provider,
            external_id=external_id,
            status=_STATE_MAP.get(state, TicketStatus.IN_PROGRESS),
            url=f"{self._base_url}/nav_to.do?uri={self._table}.do?sys_id={external_id}",
            summary=result.get("short_description"),
        )

    async def aclose(self) -> None:
        await self._client.aclose()


__all__ = ["ServiceNowTicketingAdapter", "build_servicenow_payload"]
