"""Jira ticketing adapter over the REST API (INT-004, FR-044/FR-051).

Config-driven, framework-free, and mock-testable via ``httpx.MockTransport``. v2 of the Jira REST
API is used because it accepts a plain-text description, keeping the redacted payload builder
provider-agnostic. A ticket is reported as created **only** from a confirmed 2xx create response;
any transport error or non-2xx response raises :class:`TicketCreationError`.
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

_PRIORITY_MAP = {"low": "Low", "medium": "Medium", "high": "High", "urgent": "Highest"}

_STATUS_MAP = {
    "new": TicketStatus.CREATED,
    "open": TicketStatus.CREATED,
    "to do": TicketStatus.CREATED,
    "backlog": TicketStatus.PENDING,
    "in progress": TicketStatus.IN_PROGRESS,
    "in review": TicketStatus.IN_PROGRESS,
    "done": TicketStatus.RESOLVED,
    "resolved": TicketStatus.RESOLVED,
    "closed": TicketStatus.RESOLVED,
}


def _label(value: str) -> str:
    """Jira labels cannot contain spaces or reserved characters."""
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in value)
    return cleaned.strip("-_.") or "unknown"


def build_jira_payload(
    request: TicketRequest,
    *,
    project_key: str,
    issue_type: str = "Task",
    redact: bool = True,
) -> dict[str, object]:
    """Build a Jira issue payload with a redacted description (FR-050/FR-051)."""
    return {
        "fields": {
            "project": {"key": project_key},
            "issuetype": {"name": issue_type},
            "summary": redact_text(request.summary) if redact else request.summary,
            "description": build_ticket_description(request, redact=redact),
            "priority": {"name": _PRIORITY_MAP.get(request.priority.value, "Medium")},
            "labels": ["ecom-support", _label(f"conv-{request.conversation_id}")],
        }
    }


class JiraTicketingAdapter(TicketingAdapter):
    """Creates Jira issues via the REST API (mock-backed in tests via ``httpx.MockTransport``)."""

    provider = TicketProvider.JIRA

    def __init__(
        self,
        *,
        base_url: str,
        email: str,
        api_token: str,
        project_key: str,
        issue_type: str = "Task",
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
        redact: bool = True,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._email = email
        self._api_token = api_token
        self._project_key = project_key
        self._issue_type = issue_type
        self._redact = redact
        self._client = client or httpx.AsyncClient(base_url=self._base_url, timeout=timeout)
        self._auth = (self._email, self._api_token)

    @classmethod
    def from_config(
        cls,
        config: IntegrationsConfig,
        *,
        client: httpx.AsyncClient | None = None,
        redact: bool = True,
    ) -> JiraTicketingAdapter:
        """Build from validated config; fail loudly when required values are missing."""
        base_url = config.jira_base_url
        email = config.jira_email
        api_token = config.jira_api_token
        project_key = config.jira_project_key
        missing = [
            name
            for name, value in (
                ("jira_base_url", base_url),
                ("jira_email", email),
                ("jira_api_token", api_token),
                ("jira_project_key", project_key),
            )
            if not value
        ]
        if missing:
            raise ConfigurationError(
                "Jira ticketing is not fully configured.", details={"missing": missing}
            )
        assert base_url and email and api_token and project_key  # narrowed above
        return cls(
            base_url=base_url,
            email=email,
            api_token=api_token,
            project_key=project_key,
            issue_type=config.jira_issue_type or "Task",
            client=client,
            redact=redact,
        )

    async def create_ticket(self, request: TicketRequest) -> ExternalTicket:
        payload = build_jira_payload(
            request,
            project_key=self._project_key,
            issue_type=self._issue_type,
            redact=self._redact,
        )
        try:
            response = await self._client.post("/rest/api/2/issue", json=payload, auth=self._auth)
        except httpx.HTTPError as exc:
            raise TicketCreationError(
                "Jira did not confirm ticket creation.",
                details={"provider": self.provider.value, "reason": type(exc).__name__},
            ) from exc
        if response.status_code not in (200, 201):
            raise TicketCreationError(
                "Jira did not confirm ticket creation.",
                details={"provider": self.provider.value, "status_code": response.status_code},
            )
        key = response.json().get("key")
        if not key:
            raise TicketCreationError(
                "Jira response did not include a ticket key.",
                details={"provider": self.provider.value},
            )
        return ExternalTicket(
            provider=self.provider,
            external_id=key,
            status=TicketStatus.CREATED,
            url=f"{self._base_url}/browse/{key}",
            summary=request.summary,
        )

    async def get_status(self, external_id: str) -> ExternalTicket | None:
        try:
            response = await self._client.get(
                f"/rest/api/2/issue/{external_id}",
                params={"fields": "status,summary"},
                auth=self._auth,
            )
        except httpx.HTTPError as exc:
            raise TicketingError(
                "Could not reach Jira to read ticket status.",
                details={"provider": self.provider.value, "reason": type(exc).__name__},
            ) from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise TicketingError(
                "Jira returned an unexpected status.",
                details={"provider": self.provider.value, "status_code": response.status_code},
            )
        body = response.json()
        fields = body.get("fields", {})
        status_name = str(fields.get("status", {}).get("name", "")).lower()
        key = body.get("key", external_id)
        return ExternalTicket(
            provider=self.provider,
            external_id=key,
            status=_STATUS_MAP.get(status_name, TicketStatus.IN_PROGRESS),
            url=f"{self._base_url}/browse/{key}",
            summary=fields.get("summary"),
        )

    async def aclose(self) -> None:
        await self._client.aclose()


__all__ = ["JiraTicketingAdapter", "build_jira_payload"]
