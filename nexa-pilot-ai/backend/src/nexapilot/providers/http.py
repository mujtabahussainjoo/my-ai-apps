"""Shared HTTP helpers for provider adapters.

Adapter code talks to official provider REST endpoints. Keeping the HTTP layer
here means timeouts, retries, error normalization and secret redaction behave
identically for every provider.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from nexapilot.core.errors import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from nexapilot.core.logging import get_logger

log = get_logger(__name__)

RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


def classify_status(status_code: int, provider: str, body: str = "") -> ProviderError:
    """Map an HTTP status onto the normalized provider error taxonomy."""
    if status_code in (401, 403):
        return ProviderAuthError(
            f"{provider} rejected the credentials for this configuration",
            details={"provider": provider, "status": status_code},
        )
    if status_code == 429:
        return ProviderRateLimitError(
            f"{provider} rate limit reached", details={"provider": provider, "status": status_code}
        )
    if status_code >= 500:
        return ProviderUnavailableError(
            f"{provider} is temporarily unavailable",
            details={"provider": provider, "status": status_code},
        )
    return ProviderError(
        f"{provider} returned an error response",
        details={"provider": provider, "status": status_code, "body": body[:500]},
    )


def wrap_transport_error(exc: Exception, provider: str, timeout: float) -> ProviderError:
    if isinstance(exc, httpx.TimeoutException):
        return ProviderTimeoutError(
            f"{provider} request timed out after {timeout:.0f}s",
            details={"provider": provider},
        )
    if isinstance(exc, httpx.HTTPError):
        return ProviderUnavailableError(
            f"could not reach {provider}: {type(exc).__name__}",
            details={"provider": provider},
        )
    return ProviderError(f"{provider} request failed: {type(exc).__name__}")


def build_client(
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout, connect=min(timeout, 15.0)),
        headers=headers or {},
        transport=transport,
        follow_redirects=False,
    )


async def post_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    payload: dict[str, Any],
    provider: str,
    timeout: float,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        response = await client.post(url, json=payload, headers=headers or {})
    except httpx.HTTPError as exc:
        raise wrap_transport_error(exc, provider, timeout) from exc

    if response.status_code >= 400:
        raise classify_status(response.status_code, provider, response.text)
    try:
        data = response.json()
    except ValueError as exc:
        raise ProviderError(f"{provider} returned a non-JSON response") from exc
    if not isinstance(data, dict):
        raise ProviderError(f"{provider} returned an unexpected payload shape")
    return data


async def sse_lines(response: httpx.Response) -> AsyncIterator[str]:
    """Yield raw ``data:`` payloads from a Server-Sent Events stream."""
    buffer = ""
    async for chunk in response.aiter_text():
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line or not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if payload:
                yield payload


async def sse_json(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    async for payload in sse_lines(response):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            log.warning("provider.sse.invalid_json")
            continue
        if isinstance(parsed, dict):
            yield parsed


async def ndjson(response: httpx.Response) -> AsyncIterator[dict[str, Any]]:
    """Yield JSON objects from a newline-delimited JSON stream (Ollama native API)."""
    async for line in response.aiter_lines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            log.warning("provider.ndjson.invalid_json")
            continue
        if isinstance(parsed, dict):
            yield parsed
