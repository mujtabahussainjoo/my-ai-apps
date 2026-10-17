"""Core domain model shared across the workflow.

Keeping the model in one place makes normalization, validation,
dependency mapping and adapters agree on field names and statuses.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Canonical employee field names
# ---------------------------------------------------------------------------
class Field:
    EMPLOYEE_ID = "employee_id"
    LEGAL_NAME = "legal_name"
    PREFERRED_NAME = "preferred_name"
    START_DATE = "start_date"
    WORK_LOCATION = "work_location"
    SHIPPING_ADDRESS = "shipping_address"
    DEPARTMENT = "department"
    JOB_TITLE = "job_title"
    PERSONAL_EMAIL = "personal_email"
    MANAGER = "manager"


ALL_FIELDS = [
    Field.EMPLOYEE_ID,
    Field.LEGAL_NAME,
    Field.PREFERRED_NAME,
    Field.START_DATE,
    Field.WORK_LOCATION,
    Field.SHIPPING_ADDRESS,
    Field.DEPARTMENT,
    Field.JOB_TITLE,
    Field.PERSONAL_EMAIL,
    Field.MANAGER,
]


# ---------------------------------------------------------------------------
# Target systems
# ---------------------------------------------------------------------------
class TargetSystem(str, Enum):
    WORKDAY = "workday"
    OKTA = "okta"
    GOOGLE_WORKSPACE = "google_workspace"
    SLACK = "slack"
    EQUIPMENT = "equipment"
    COHORT_TRACKER = "cohort_tracker"


# ---------------------------------------------------------------------------
# Statuses
# ---------------------------------------------------------------------------
class OperationStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    SKIPPED_IDEMPOTENT = "SKIPPED_IDEMPOTENT"
    RETRY_PENDING = "RETRY_PENDING"
    FAILED_TEMPORARY = "FAILED_TEMPORARY"
    FAILED_PERMANENT = "FAILED_PERMANENT"
    UNKNOWN = "UNKNOWN"


class FailureKind(str, Enum):
    TEMPORARY = "temporary"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


class OverallStatus(str, Enum):
    COMPLETED = "COMPLETED"
    IN_PROGRESS = "IN_PROGRESS"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    PARTIALLY_COMPLETED = "PARTIALLY_COMPLETED"
    FAILED = "FAILED"


class TaskStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    OVERDUE = "OVERDUE"
    EXEMPT = "EXEMPT"


# Tasks in these states are considered "done" by the deadline monitor.
CLOSED_TASK_STATUSES = {TaskStatus.COMPLETE.value, TaskStatus.EXEMPT.value}


# ---------------------------------------------------------------------------
# Incoming event
# ---------------------------------------------------------------------------
@dataclass
class RawEvent:
    """A hiring or employee-change event as received from a source system."""

    event_id: str
    source: str
    employee_id: str
    event_type: str
    changed_fields: list[str] = field(default_factory=list)
    employee: dict[str, Any] = field(default_factory=dict)
    approved: bool = True
    received_at: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RawEvent":
        return cls(
            event_id=str(payload.get("event_id", "")),
            source=str(payload.get("source", "")),
            employee_id=str(payload.get("employee_id", "")),
            event_type=str(payload.get("event_type", "")),
            changed_fields=list(payload.get("changed_fields", []) or []),
            employee=dict(payload.get("employee", {}) or {}),
            approved=bool(payload.get("approved", True)),
            received_at=payload.get("received_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Canonical employee record
# ---------------------------------------------------------------------------
@dataclass
class StandardEmployee:
    """The single internal representation every source normalizes into."""

    employee_id: str = ""
    legal_name: str = ""
    preferred_name: str = ""
    start_date: str = ""
    work_location: str = ""
    shipping_address: str = ""
    department: str = ""
    job_title: str = ""
    personal_email: str = ""
    manager: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StandardEmployee":
        return cls(**{k: data.get(k, "") or "" for k in ALL_FIELDS})

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in ALL_FIELDS}

    def changed_fields(self, previous: "StandardEmployee") -> list[str]:
        """Return the canonical fields whose value differs from ``previous``."""
        diff: list[str] = []
        for name in ALL_FIELDS:
            if getattr(self, name) != getattr(previous, name):
                diff.append(name)
        return diff


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
@dataclass
class ValidationIssue:
    field_name: str
    code: str
    message: str
    incoming_value: Any = None
    authoritative_value: Any = None
    blocked_targets: list[TargetSystem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["blocked_targets"] = [t.value for t in self.blocked_targets]
        return data


@dataclass
class ValidationResult:
    issues: list[ValidationIssue] = field(default_factory=list)
    blocked_fields: set[str] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [i.to_dict() for i in self.issues],
            "blocked_fields": sorted(self.blocked_fields),
        }


# ---------------------------------------------------------------------------
# Operations / ledger / exceptions
# ---------------------------------------------------------------------------
@dataclass
class OperationRecord:
    """A row in the idempotency ledger for one target operation."""

    operation_key: str
    employee_id: str
    event_id: str
    target: str
    operation: str
    status: str = OperationStatus.PENDING.value
    attempts: int = 0
    last_error: str | None = None
    failure_kind: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OperationRecord":
        return cls(**data)


@dataclass
class ExceptionRecord:
    employee_id: str
    event_id: str
    exception_type: str
    reason: str
    exception_id: str = ""
    field_name: str | None = None
    source_values: dict[str, Any] = field(default_factory=dict)
    recommended_action: str | None = None
    ai_used: bool = False
    status: str = "OPEN"
    created_at: str | None = None
    resolved_by: str | None = None
    resolution: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExceptionRecord":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class OperationOutcome:
    """Result of attempting one target operation."""

    target: str
    operation: str
    status: str
    detail: str = ""
    attempts: int = 1
    failure_kind: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OnboardingTask:
    """A monitored onboarding task (hardware, background check, etc.)."""

    task_id: str
    employee_id: str
    name: str
    owner: str
    due_date: str
    status: str = TaskStatus.NOT_STARTED.value
    reminder_history: list[str] = field(default_factory=list)
    last_reminded_at: str | None = None
    notes: str = ""

    @property
    def is_open(self) -> bool:
        return self.status not in CLOSED_TASK_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OnboardingTask":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})
