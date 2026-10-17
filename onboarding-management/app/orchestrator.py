"""The orchestrator: the core change-propagation workflow.

    receive -> normalize -> validate -> plan -> (idempotency) -> update
    -> verify -> retry/reconcile -> record per-target status -> overall state

Validation issues and unrecoverable failures are persisted as exceptions
via :class:`ExceptionHandler`. Retries/reconciliation are delegated to
:class:`RetryHandler`. Audit logging and AI assistance plug in later as
additional collaborators without changing this flow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from adapters.client import DemoPortalClient
from app.ai_helper import AIHelper
from app.audit_logger import AuditLogger
from app.authoritative_store import AuthoritativeStore
from app.dependency_mapper import (
    DependencyMapper,
    PropagationPlan,
    TargetPlan,
    compute_changed_fields,
)
from app.event_receiver import MalformedEventError, parse_event
from app.exception_handler import ExceptionHandler
from app.idempotency_store import IdempotencyStore
from app.models import (
    OperationOutcome,
    OperationStatus,
    OverallStatus,
    RawEvent,
    StandardEmployee,
)
from app.normalizer import normalize_employee
from app.retry_handler import AttemptResult, RetryHandler
from app.targets import TARGET_SPECS
from app.validator import RECORD_FIELD, Validator

_SUCCESS_STATUSES = {
    OperationStatus.SUCCESS.value,
    OperationStatus.SKIPPED_IDEMPOTENT.value,
}


@dataclass
class WorkflowResult:
    event_id: str
    employee_id: str
    source: str
    event_type: str
    overall_status: OverallStatus
    changed_fields: list[str] = field(default_factory=list)
    outcomes: list[OperationOutcome] = field(default_factory=list)
    blocked: dict[str, list[str]] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)
    exceptions: list[str] = field(default_factory=list)
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "employee_id": self.employee_id,
            "source": self.source,
            "event_type": self.event_type,
            "overall_status": self.overall_status.value,
            "changed_fields": self.changed_fields,
            "outcomes": [o.to_dict() for o in self.outcomes],
            "blocked": self.blocked,
            "validation": self.validation,
            "plan": self.plan,
            "exceptions": self.exceptions,
            "message": self.message,
        }


class Orchestrator:
    def __init__(
        self,
        *,
        portal: DemoPortalClient | None = None,
        ledger: IdempotencyStore | None = None,
        store: AuthoritativeStore | None = None,
        mapper: DependencyMapper | None = None,
        validator: Validator | None = None,
        retry_handler: RetryHandler | None = None,
        exception_handler: ExceptionHandler | None = None,
        audit: AuditLogger | None = None,
        ai: AIHelper | None = None,
    ) -> None:
        self.portal = portal or DemoPortalClient()
        self.ledger = ledger or IdempotencyStore()
        self.store = store or AuthoritativeStore()
        self.mapper = mapper or DependencyMapper()
        self.validator = validator or Validator(self.store)
        self.retry = retry_handler or RetryHandler()
        self.exceptions = exception_handler or ExceptionHandler()
        self.audit = audit or AuditLogger()
        self.ai = ai or AIHelper()

    # -- entry points ------------------------------------------------------
    def process(self, event: RawEvent) -> WorkflowResult:
        employee = normalize_employee(event)
        previous = self.store.get(event.employee_id)
        changed = compute_changed_fields(event, employee, previous)
        validation = self.validator.validate(event, employee)

        exception_ids = self._record_validation_exceptions(event, employee, validation)

        plan = self.mapper.plan(changed, validation)
        outcomes: list[OperationOutcome] = []
        for target, target_plan in plan.targets.items():
            if not target_plan.actionable:
                continue
            outcome = self._execute_target(event, employee, target, target_plan)
            outcomes.append(outcome)

        blocked = {
            name: p.blocked_fields for name, p in plan.blocked_targets().items()
        }
        overall = self._overall_status(plan, outcomes)

        result = WorkflowResult(
            event_id=event.event_id,
            employee_id=employee.employee_id,
            source=event.source,
            event_type=event.event_type,
            overall_status=overall,
            changed_fields=changed,
            outcomes=outcomes,
            blocked=blocked,
            validation=validation.to_dict(),
            plan=plan.to_dict(),
            exceptions=exception_ids,
            message=self._message(overall, outcomes, blocked),
        )

        self.audit.log_workflow(
            result=result,
            event=event,
            employee_before=previous.to_dict() if previous else None,
            employee_after=employee.to_dict(),
        )
        return result

    def handle(self, payload: Any) -> WorkflowResult:
        """Parse a raw dict, rejecting malformed events gracefully."""
        try:
            event = parse_event(payload)
        except MalformedEventError as exc:
            return WorkflowResult(
                event_id=str(payload.get("event_id", "")) if isinstance(payload, dict) else "",
                employee_id="",
                source="",
                event_type="malformed",
                overall_status=OverallStatus.FAILED,
                message=f"rejected malformed event: {exc}",
            )
        return self.process(event)

    # -- validation exceptions --------------------------------------------
    def _record_validation_exceptions(
        self, event: RawEvent, employee: StandardEmployee, validation
    ) -> list[str]:
        ids: list[str] = []
        for issue in validation.issues:
            field_name = None if issue.field_name == RECORD_FIELD else issue.field_name
            classification = self.ai.classify(
                exception_type=issue.code,
                reason=issue.message,
                field_name=field_name,
            )
            record = self.exceptions.open_exception(
                employee_id=employee.employee_id,
                event_id=event.event_id,
                exception_type=issue.code,
                reason=issue.message,
                field_name=field_name,
                source_values={
                    "incoming": issue.incoming_value,
                    "authoritative": issue.authoritative_value,
                },
                recommended_action=classification.recommended_action,
                ai_used=classification.ai_used,
            )
            ids.append(record.exception_id)
        return ids

    # -- target execution --------------------------------------------------
    def _execute_target(
        self,
        event: RawEvent,
        employee: StandardEmployee,
        target: str,
        target_plan: TargetPlan,
    ) -> OperationOutcome:
        operation = TARGET_SPECS[target]["operation"]
        key = self.ledger.operation_key(
            employee.employee_id, event.event_id, target, operation
        )

        if self.ledger.is_done(key):
            self.ledger.mark_skipped(
                employee.employee_id, event.event_id, target, operation
            )
            return OperationOutcome(
                target=target,
                operation=operation,
                status=OperationStatus.SKIPPED_IDEMPOTENT.value,
                detail="already completed for this event",
                attempts=0,
            )

        data = {name: getattr(employee, name) for name in target_plan.allowed_fields}

        def attempt_fn():
            return self.portal.write(
                target,
                employee.employee_id,
                event_id=event.event_id,
                operation_key=key,
                data=data,
            )

        def check_fn() -> bool:
            verify = self.portal.verify(target, employee.employee_id)
            return verify.ok and verify.exists

        attempt = self.retry.run(attempt_fn, check_fn)
        status = self._status_from(attempt)
        detail = attempt.result.detail

        self.ledger.record(
            employee.employee_id,
            event.event_id,
            target,
            operation,
            status,
            error=None if status is OperationStatus.SUCCESS else detail,
            failure_kind=attempt.result.failure_kind,
            attempt_delta=attempt.attempts,
        )

        if status is not OperationStatus.SUCCESS and attempt.needs_escalation:
            self._escalate(event, employee, target, operation, attempt, status)

        return OperationOutcome(
            target=target,
            operation=operation,
            status=status.value,
            detail=detail,
            attempts=attempt.attempts,
            failure_kind=(
                attempt.result.failure_kind.value
                if attempt.result.failure_kind
                else None
            ),
            payload=data,
        )

    @staticmethod
    def _status_from(attempt: AttemptResult) -> OperationStatus:
        if attempt.ok:
            return OperationStatus.SUCCESS
        if attempt.permanent:
            return OperationStatus.FAILED_PERMANENT
        return OperationStatus.RETRY_PENDING

    def _escalate(
        self,
        event: RawEvent,
        employee: StandardEmployee,
        target: str,
        operation: str,
        attempt: AttemptResult,
        status: OperationStatus,
    ) -> None:
        if attempt.permanent:
            exception_type = "propagation_permanent_failure"
            reason = f"{target}/{operation}: {attempt.result.detail}"
        else:
            exception_type = "retry_exhausted"
            reason = (
                f"{target}/{operation}: retries exhausted after "
                f"{attempt.attempts} attempts: {attempt.result.detail}"
            )
        classification = self.ai.classify(
            exception_type=exception_type, reason=reason
        )
        self.exceptions.open_exception(
            employee_id=employee.employee_id,
            event_id=event.event_id,
            exception_type=exception_type,
            reason=reason,
            source_values={
                "target": target,
                "operation": operation,
                "status": status.value,
                "attempts": attempt.attempts,
            },
            recommended_action=classification.recommended_action,
            ai_used=classification.ai_used,
        )

    # -- overall status ----------------------------------------------------
    def _overall_status(
        self, plan: PropagationPlan, outcomes: list[OperationOutcome]
    ) -> OverallStatus:
        blocked = plan.blocked_targets()
        if plan.record_blocked:
            return OverallStatus.NEEDS_REVIEW

        statuses = {o.status for o in outcomes}
        has_success = bool(statuses & _SUCCESS_STATUSES)

        if blocked:
            return OverallStatus.NEEDS_REVIEW
        if not outcomes:
            return OverallStatus.COMPLETED
        if statuses <= _SUCCESS_STATUSES:
            return OverallStatus.COMPLETED
        if has_success:
            return OverallStatus.PARTIALLY_COMPLETED
        if OperationStatus.RETRY_PENDING.value in statuses:
            return OverallStatus.IN_PROGRESS
        return OverallStatus.FAILED

    @staticmethod
    def _message(
        overall: OverallStatus,
        outcomes: list[OperationOutcome],
        blocked: dict[str, list[str]],
    ) -> str:
        if overall is OverallStatus.NEEDS_REVIEW:
            targets = ", ".join(blocked) or "record"
            return f"human review required for: {targets}"
        if overall is OverallStatus.COMPLETED:
            return "all required systems updated"
        failed = [
            o.target
            for o in outcomes
            if o.status == OperationStatus.FAILED_PERMANENT.value
        ]
        pending = [
            o.target
            for o in outcomes
            if o.status == OperationStatus.RETRY_PENDING.value
        ]
        parts = []
        if failed:
            parts.append(f"failed: {', '.join(failed)}")
        if pending:
            parts.append(f"pending retry: {', '.join(pending)}")
        return "; ".join(parts) or overall.value


def default_orchestrator() -> Orchestrator:
    return Orchestrator()
