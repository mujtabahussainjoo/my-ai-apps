"""Map changed fields to the systems that depend on them.

Two responsibilities:
* invert the field -> systems dependency table into a concrete plan for
  one event;
* keep a target actionable even when *other* fields are blocked, while
  never pushing a disputed field. A target with no safe fields left is
  blocked instead of failing blindly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import (
    ALL_FIELDS,
    Field,
    RawEvent,
    StandardEmployee,
    TargetSystem,
    ValidationResult,
)
from app.normalizer import normalize_changed_fields

WORKDAY = TargetSystem.WORKDAY
OKTA = TargetSystem.OKTA
GOOGLE = TargetSystem.GOOGLE_WORKSPACE
SLACK = TargetSystem.SLACK
EQUIPMENT = TargetSystem.EQUIPMENT
TRACKER = TargetSystem.COHORT_TRACKER

ALL_TARGETS = {
    WORKDAY,
    OKTA,
    GOOGLE,
    SLACK,
    EQUIPMENT,
    TRACKER,
}

# Which systems depend on each canonical field.
# The cohort tracker is intentionally included everywhere: it tracks
# onboarding progress for every change.
FIELD_DEPENDENCIES: dict[str, set[TargetSystem]] = {
    Field.EMPLOYEE_ID: ALL_TARGETS,
    Field.LEGAL_NAME: {WORKDAY, OKTA, GOOGLE, SLACK, TRACKER},
    Field.PREFERRED_NAME: {OKTA, GOOGLE, SLACK, TRACKER},
    Field.START_DATE: {WORKDAY, OKTA, GOOGLE, EQUIPMENT, TRACKER},
    Field.WORK_LOCATION: {WORKDAY, EQUIPMENT, TRACKER},
    Field.SHIPPING_ADDRESS: {EQUIPMENT, TRACKER},
    Field.DEPARTMENT: {WORKDAY, OKTA, SLACK, TRACKER},
    Field.JOB_TITLE: {WORKDAY, OKTA, TRACKER},
    Field.PERSONAL_EMAIL: {TRACKER},
    Field.MANAGER: {WORKDAY, OKTA, SLACK, TRACKER},
}


def targets_for_field(name: str) -> set[TargetSystem]:
    return set(FIELD_DEPENDENCIES.get(name, set()))


def compute_changed_fields(
    event: RawEvent,
    employee: StandardEmployee,
    previous: StandardEmployee | None = None,
) -> list[str]:
    """Determine the effective set of changed canonical fields.

    Preference order: the event's declared ``changed_fields`` (the source
    tells us what changed), then an actual diff against the previous
    record, then every populated field (new-hire full payload).

    An empty incoming value means "not supplied", not "cleared", so it is
    never treated as a change.
    """
    declared = normalize_changed_fields(event.changed_fields)
    if declared:
        return declared

    if previous is not None:
        diff = [
            name
            for name in ALL_FIELDS
            if getattr(employee, name)
            and getattr(employee, name) != getattr(previous, name)
        ]
        if diff:
            return diff

    return [name for name in ALL_FIELDS if getattr(employee, name)]


@dataclass
class TargetPlan:
    target: TargetSystem
    fields: list[str] = field(default_factory=list)
    allowed_fields: list[str] = field(default_factory=list)
    blocked_fields: list[str] = field(default_factory=list)

    @property
    def actionable(self) -> bool:
        return bool(self.allowed_fields)

    @property
    def blocked(self) -> bool:
        return bool(self.blocked_fields)


@dataclass
class PropagationPlan:
    changed_fields: list[str]
    targets: dict[str, TargetPlan]
    record_blocked: bool = False

    def target_plan(self, target: TargetSystem | str) -> TargetPlan | None:
        key = target.value if isinstance(target, TargetSystem) else target
        return self.targets.get(key)

    def actionable_targets(self) -> dict[str, TargetPlan]:
        return {k: p for k, p in self.targets.items() if p.actionable}

    def blocked_targets(self) -> dict[str, TargetPlan]:
        return {k: p for k, p in self.targets.items() if p.blocked}

    def to_dict(self) -> dict[str, object]:
        return {
            "changed_fields": self.changed_fields,
            "record_blocked": self.record_blocked,
            "targets": {
                k: {
                    "fields": p.fields,
                    "allowed_fields": p.allowed_fields,
                    "blocked_fields": p.blocked_fields,
                }
                for k, p in self.targets.items()
            },
        }


class DependencyMapper:
    def plan(
        self, changed_fields: list[str], validation: ValidationResult
    ) -> PropagationPlan:
        blocked = set(validation.blocked_fields)
        record_blocked = "__record__" in blocked

        # target -> (fields, allowed, blocked)
        collected: dict[str, TargetPlan] = {}
        for name in changed_fields:
            if name not in FIELD_DEPENDENCIES:
                continue
            is_blocked = record_blocked or name in blocked
            for target in FIELD_DEPENDENCIES[name]:
                plan = collected.setdefault(target.value, TargetPlan(target=target))
                plan.fields.append(name)
                if is_blocked:
                    plan.blocked_fields.append(name)
                else:
                    plan.allowed_fields.append(name)

        return PropagationPlan(
            changed_fields=list(changed_fields),
            targets=collected,
            record_blocked=record_blocked,
        )


def default_mapper() -> DependencyMapper:
    return DependencyMapper()
