"""HTTP adapters that call the local demo portal.

An adapter performs exactly **one** attempt and classifies the result.
Retrying, backoff and reconciliation are the retry handler's job - this
keeps a clean separation between "talk to a system" and "decide what to
do about failures".

The ``httpx`` client can be injected so tests can drive the FastAPI app
in-process (via ``httpx.ASGITransport``) with no real network.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import httpx

from app.config import settings
from app.models import FailureKind, OperationStatus, TargetSystem
from app.targets import TARGET_SPECS

# HTTP status -> (OperationStatus, FailureKind)
_PERMANENT_CODES = {400, 401, 403, 404, 405, 409, 422}
_UNKNOWN_CODES = {504}


@dataclass
class TargetResult:
    """Outcome of a single adapter call."""

    target: str
    operation: str
    status: OperationStatus
    http_status: int | None = None
    detail: str = ""
    failure_kind: FailureKind | None = None
    applied: bool = False
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status is OperationStatus.SUCCESS

    @property
    def retryable(self) -> bool:
        return self.failure_kind is FailureKind.TEMPORARY

    @property
    def permanent(self) -> bool:
        return self.failure_kind is FailureKind.PERMANENT

    @property
    def needs_reconciliation(self) -> bool:
        return self.failure_kind is FailureKind.UNKNOWN

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["failure_kind"] = self.failure_kind.value if self.failure_kind else None
        return data


@dataclass
class VerifyResult:
    """Result of reading a target back to check the stored state."""

    target: str
    employee_id: str
    ok: bool
    exists: bool = False
    http_status: int | None = None
    detail: str = ""
    record: dict[str, Any] | None = None


class DemoPortalClient:
    def __init__(
        self,
        base_url: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.base_url = (base_url or settings.demo_portal_url).rstrip("/")
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(base_url=self.base_url, timeout=self.timeout)
        return self._client

    # -- writes ------------------------------------------------------------
    def write(
        self,
        target: str | TargetSystem,
        employee_id: str,
        *,
        event_id: str | None = None,
        operation_key: str | None = None,
        data: dict[str, Any] | None = None,
        operation: str | None = None,
    ) -> TargetResult:
        target_value = target.value if isinstance(target, TargetSystem) else target
        spec = TARGET_SPECS[target_value]
        op = operation or spec["operation"]
        path = f"/{target_value}/{spec['resource']}"
        body = {
            "employee_id": employee_id,
            "event_id": event_id,
            "operation_key": operation_key,
            "data": data or {},
        }

        try:
            response = self.client.post(path, json=body)
        except httpx.TimeoutException as exc:
            return TargetResult(
                target=target_value,
                operation=op,
                status=OperationStatus.UNKNOWN,
                failure_kind=FailureKind.UNKNOWN,
                detail=f"client timeout: {exc}",
            )
        except httpx.RequestError as exc:
            return TargetResult(
                target=target_value,
                operation=op,
                status=OperationStatus.FAILED_TEMPORARY,
                failure_kind=FailureKind.TEMPORARY,
                detail=f"connection error: {exc}",
            )

        return self._classify_write(target_value, op, response)

    def _classify_write(
        self, target: str, operation: str, response: httpx.Response
    ) -> TargetResult:
        code = response.status_code
        payload = self._safe_json(response)

        if 200 <= code < 300:
            return TargetResult(
                target=target,
                operation=operation,
                status=OperationStatus.SUCCESS,
                http_status=code,
                detail="ok",
                applied=True,
                payload=payload,
            )
        if code in _PERMANENT_CODES:
            return TargetResult(
                target=target,
                operation=operation,
                status=OperationStatus.FAILED_PERMANENT,
                http_status=code,
                failure_kind=FailureKind.PERMANENT,
                detail=self._detail(payload, response),
            )
        if code in _UNKNOWN_CODES:
            return TargetResult(
                target=target,
                operation=operation,
                status=OperationStatus.UNKNOWN,
                http_status=code,
                failure_kind=FailureKind.UNKNOWN,
                detail=self._detail(payload, response),
            )
        # Anything else (429, 5xx, unexpected) is treated as a temporary
        # failure and is safe to retry with backoff.
        return TargetResult(
            target=target,
            operation=operation,
            status=OperationStatus.FAILED_TEMPORARY,
            http_status=code,
            failure_kind=FailureKind.TEMPORARY,
            detail=self._detail(payload, response),
        )

    # -- verification / reconciliation ------------------------------------
    def verify(self, target: str | TargetSystem, employee_id: str) -> VerifyResult:
        target_value = target.value if isinstance(target, TargetSystem) else target
        spec = TARGET_SPECS[target_value]
        path = f"/{target_value}/{spec['resource']}/{employee_id}"
        try:
            response = self.client.get(path)
        except httpx.RequestError as exc:
            return VerifyResult(
                target=target_value,
                employee_id=employee_id,
                ok=False,
                detail=f"connection error: {exc}",
            )

        if response.status_code == 404:
            return VerifyResult(
                target=target_value,
                employee_id=employee_id,
                ok=True,
                exists=False,
                http_status=404,
                detail="not present",
            )
        if 200 <= response.status_code < 300:
            payload = self._safe_json(response)
            return VerifyResult(
                target=target_value,
                employee_id=employee_id,
                ok=True,
                exists=True,
                http_status=response.status_code,
                detail="present",
                record=payload.get("record", payload),
            )
        return VerifyResult(
            target=target_value,
            employee_id=employee_id,
            ok=False,
            http_status=response.status_code,
            detail=f"verify failed with status {response.status_code}",
        )

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _safe_json(response: httpx.Response) -> dict[str, Any]:
        try:
            data = response.json()
            return data if isinstance(data, dict) else {"value": data}
        except ValueError:
            return {}

    @staticmethod
    def _detail(payload: dict[str, Any], response: httpx.Response) -> str:
        return str(payload.get("detail") or response.text or response.reason_phrase)

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()

    def __enter__(self) -> "DemoPortalClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
