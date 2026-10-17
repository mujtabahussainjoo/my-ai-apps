"""Deterministic validation - the safety gate before any propagation.

Every rule here is explicit and testable. AI is never consulted here;
validation must work even when the AI helper is unavailable.
"""

from __future__ import annotations

import re
from datetime import date

from app.authoritative_store import AuthoritativeStore
from app.models import (
    ALL_FIELDS,
    Field,
    RawEvent,
    StandardEmployee,
    ValidationIssue,
    ValidationResult,
)

# Record-level issues block every downstream action.
RECORD_FIELD = "__record__"

REQUIRED_FIELDS = [Field.EMPLOYEE_ID, Field.LEGAL_NAME, Field.START_DATE]

ALLOWED_LOCATIONS = {
    "Bangalore",
    "Hyderabad",
    "Gurgaon",
    "Mumbai",
    "Pune",
    "London",
    "Remote",
}

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Fields a non-authoritative source may legitimately change after an offer.
# Anything else is considered protected and a divergence triggers review.
SOURCE_MUTABLE_FIELDS: dict[str, set[str]] = {
    "ashby": {
        Field.START_DATE,
        Field.SHIPPING_ADDRESS,
        Field.PREFERRED_NAME,
        Field.PERSONAL_EMAIL,
        Field.MANAGER,
    },
    "workday_intake": set(ALL_FIELDS),
    "workday": set(ALL_FIELDS),
    "hr": set(ALL_FIELDS),
}

DEFAULT_MUTABLE_FIELDS = {Field.SHIPPING_ADDRESS, Field.PREFERRED_NAME}

NEW_HIRE_EVENT_TYPES = {"new_hire", "new_hire_off_cycle"}


class Validator:
    def __init__(self, store: AuthoritativeStore | None = None) -> None:
        self.store = store or AuthoritativeStore()

    def validate(self, event: RawEvent, employee: StandardEmployee) -> ValidationResult:
        issues: list[ValidationIssue] = []
        blocked: set[str] = set()

        def add(issue: ValidationIssue) -> None:
            issues.append(issue)
            if issue.field_name:
                blocked.add(issue.field_name)

        self._check_required(employee, add)
        self._check_format(employee, add)
        self._check_allowed_values(employee, add)
        self._check_business_rules(event, add)
        authoritative = self._check_duplicate(event, add)
        if authoritative is not None:
            self._check_cross_system(event, employee, authoritative, add)

        return ValidationResult(issues=issues, blocked_fields=blocked)

    # -- individual rule groups -------------------------------------------
    def _check_required(self, employee: StandardEmployee, add) -> None:
        for name in REQUIRED_FIELDS:
            if not getattr(employee, name):
                add(
                    ValidationIssue(
                        field_name=name,
                        code="missing_required",
                        message=f"Required field '{name}' is missing",
                    )
                )

    def _check_format(self, employee: StandardEmployee, add) -> None:
        if employee.start_date:
            try:
                date.fromisoformat(employee.start_date)
            except ValueError:
                add(
                    ValidationIssue(
                        field_name=Field.START_DATE,
                        code="invalid_date",
                        message="Start date must be a valid YYYY-MM-DD date",
                        incoming_value=employee.start_date,
                    )
                )
        if employee.shipping_address and len(employee.shipping_address) < 10:
            add(
                ValidationIssue(
                    field_name=Field.SHIPPING_ADDRESS,
                    code="incomplete_address",
                    message="Shipping address is too short to be complete",
                    incoming_value=employee.shipping_address,
                )
            )
        if employee.personal_email and not EMAIL_RE.match(employee.personal_email):
            add(
                ValidationIssue(
                    field_name=Field.PERSONAL_EMAIL,
                    code="invalid_email",
                    message="Personal email is not a valid address",
                    incoming_value=employee.personal_email,
                )
            )

    def _check_allowed_values(self, employee: StandardEmployee, add) -> None:
        if employee.work_location and employee.work_location not in ALLOWED_LOCATIONS:
            add(
                ValidationIssue(
                    field_name=Field.WORK_LOCATION,
                    code="unknown_location",
                    message=f"Location '{employee.work_location}' is not recognized",
                    incoming_value=employee.work_location,
                )
            )

    def _check_business_rules(self, event: RawEvent, add) -> None:
        if not event.approved:
            add(
                ValidationIssue(
                    field_name=RECORD_FIELD,
                    code="not_approved",
                    message="Hiring record is not approved; changes are not allowed",
                )
            )

    def _check_duplicate(
        self, event: RawEvent, add
    ) -> StandardEmployee | None:
        authoritative = self.store.get(event.employee_id)
        if event.event_type in NEW_HIRE_EVENT_TYPES and authoritative is not None:
            add(
                ValidationIssue(
                    field_name=Field.EMPLOYEE_ID,
                    code="duplicate_employee",
                    message=f"Employee '{event.employee_id}' already exists",
                    incoming_value=event.employee_id,
                )
            )
            return None
        return authoritative

    def _check_cross_system(
        self,
        event: RawEvent,
        employee: StandardEmployee,
        authoritative: StandardEmployee,
        add,
    ) -> None:
        mutable = SOURCE_MUTABLE_FIELDS.get(
            event.source.lower(), DEFAULT_MUTABLE_FIELDS
        )
        for name in ALL_FIELDS:
            incoming = getattr(employee, name)
            if not incoming:
                continue
            if incoming == getattr(authoritative, name):
                continue
            if name in mutable:
                continue
            add(
                ValidationIssue(
                    field_name=name,
                    code="cross_system_conflict",
                    message=(
                        f"Incoming '{name}' conflicts with the authoritative "
                        f"record and source '{event.source}' may not change it"
                    ),
                    incoming_value=incoming,
                    authoritative_value=getattr(authoritative, name),
                )
            )


def default_validator() -> Validator:
    return Validator()
