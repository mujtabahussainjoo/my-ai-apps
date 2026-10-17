"""Bounded retry with exponential backoff and reconciliation.

Handles the three failure classes from the brief:

* **temporary** (timeout/rate limit/5xx) - retry with backoff up to a
  maximum attempt count;
* **unknown outcome** (e.g. a 504 after the write may have applied) -
  reconcile with the target before retrying;
* **permanent** (invalid field / rejected business rule) - never retry.

The ``sleep`` callable is injectable so tests run instantly.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from adapters.client import TargetResult
from app.config import settings
from app.models import FailureKind, OperationStatus

AttemptFn = Callable[[], TargetResult]
CheckFn = Callable[[], bool]


@dataclass
class AttemptResult:
    result: TargetResult
    attempts: int
    reconciled: bool = False
    exhausted: bool = False

    @property
    def ok(self) -> bool:
        return self.result.status is OperationStatus.SUCCESS

    @property
    def permanent(self) -> bool:
        return self.result.failure_kind is FailureKind.PERMANENT

    @property
    def needs_escalation(self) -> bool:
        """Permanent failures and exhausted retries both need a human."""
        return self.permanent or self.exhausted


class RetryHandler:
    def __init__(
        self,
        max_retries: int | None = None,
        base_delay: float | None = None,
        sleep: Callable[[float], None] | None = None,
        max_delay: float = 5.0,
    ) -> None:
        self.max_retries = (
            settings.max_retries if max_retries is None else max_retries
        )
        self.base_delay = (
            settings.retry_base_delay_seconds if base_delay is None else base_delay
        )
        self.max_delay = max_delay
        self.sleep = sleep or time.sleep

    def backoff(self, attempt: int) -> float:
        return min(self.base_delay * (2 ** (attempt - 1)), self.max_delay)

    def run(self, attempt_fn: AttemptFn, check_fn: CheckFn | None = None) -> AttemptResult:
        attempt = 0
        while True:
            attempt += 1
            result = attempt_fn()

            if result.ok:
                if check_fn is None or check_fn():
                    return AttemptResult(result, attempt)
                result = self._as_temporary(result, "write accepted but verify failed")
            elif result.needs_reconciliation:
                if check_fn is not None and check_fn():
                    return AttemptResult(
                        TargetResult(
                            target=result.target,
                            operation=result.operation,
                            status=OperationStatus.SUCCESS,
                            applied=True,
                            detail="reconciled: target already applied the change",
                        ),
                        attempt,
                        reconciled=True,
                    )
                # Unknown and not applied yet -> safe to retry.
            elif result.permanent:
                return AttemptResult(result, attempt)

            if attempt > self.max_retries:
                return AttemptResult(result, attempt, exhausted=True)
            self.sleep(self.backoff(attempt))

    @staticmethod
    def _as_temporary(result: TargetResult, detail: str) -> TargetResult:
        return TargetResult(
            target=result.target,
            operation=result.operation,
            status=OperationStatus.FAILED_TEMPORARY,
            http_status=result.http_status,
            failure_kind=FailureKind.TEMPORARY,
            detail=detail,
        )
