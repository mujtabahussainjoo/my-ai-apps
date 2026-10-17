"""Deadline monitoring for open onboarding tasks.

Reads open tasks, computes time-to-deadline, flags approaching/overdue
tasks and reminds the responsible owner -- without sending duplicate
reminders on every run (a cadence is enforced per task).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, Protocol

from app.config import settings
from app.models import OnboardingTask
from app.task_store import TaskStore


@dataclass
class Reminder:
    task_id: str
    employee_id: str
    name: str
    owner: str
    due_date: str
    days_remaining: int
    overdue: bool
    message: str


class Notifier(Protocol):
    def __call__(self, reminder: Reminder) -> None: ...


class RecordingNotifier:
    """Collects reminders in memory (used by tests)."""

    def __init__(self) -> None:
        self.sent: list[Reminder] = []

    def __call__(self, reminder: Reminder) -> None:
        self.sent.append(reminder)


class ConsoleNotifier:
    def __call__(self, reminder: Reminder) -> None:
        print(f"[reminder] {reminder.message}")


@dataclass
class MonitorEntry:
    task_id: str
    employee_id: str
    name: str
    owner: str
    due_date: str
    status: str
    days_remaining: int
    action: str
    reminded: bool
    overdue: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class MonitorReport:
    as_of: str
    entries: list[MonitorEntry] = field(default_factory=list)
    reminders_sent: int = 0

    @property
    def approaching(self) -> int:
        return sum(1 for e in self.entries if e.action == "remind_owner")

    @property
    def overdue(self) -> int:
        return sum(1 for e in self.entries if e.overdue)

    def to_dict(self) -> dict[str, object]:
        return {
            "as_of": self.as_of,
            "reminders_sent": self.reminders_sent,
            "approaching": self.approaching,
            "overdue": self.overdue,
            "entries": [e.to_dict() for e in self.entries],
        }


class DeadlineMonitor:
    def __init__(
        self,
        store: TaskStore | None = None,
        notifier: Notifier | None = None,
        now_fn: Callable[[], datetime] | None = None,
        warn_days: int | None = None,
        reminder_interval_hours: int | None = None,
    ) -> None:
        self.store = store or TaskStore()
        self.notifier = notifier or ConsoleNotifier()
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc))
        self.warn_days = (
            settings.deadline_warn_days if warn_days is None else warn_days
        )
        self.reminder_interval_hours = (
            settings.reminder_interval_hours
            if reminder_interval_hours is None
            else reminder_interval_hours
        )

    def run(self, as_of: date | None = None) -> MonitorReport:
        today = as_of or self.now_fn().date()
        report = MonitorReport(as_of=today.isoformat())

        for task in sorted(self.store.open_tasks(), key=lambda t: t.due_date):
            days, overdue, action = self._evaluate(task, today)

            reminded = False
            if action != "monitor" and self._reminder_due(task):
                reminder = self._build_reminder(task, days, overdue)
                self.notifier(reminder)
                self.store.record_reminder(task.task_id, self.now_fn().isoformat())
                report.reminders_sent += 1
                reminded = True

            report.entries.append(
                MonitorEntry(
                    task_id=task.task_id,
                    employee_id=task.employee_id,
                    name=task.name,
                    owner=task.owner,
                    due_date=task.due_date,
                    status=task.status,
                    days_remaining=days,
                    action=action,
                    reminded=reminded,
                    overdue=overdue,
                )
            )
        return report

    def preview(self, as_of: date | None = None) -> MonitorReport:
        """Build the report **without** sending reminders (read-only view).

        Used by the dashboard so opening a page never triggers a reminder;
        :meth:`run` remains the side-effecting job.
        """
        today = as_of or self.now_fn().date()
        report = MonitorReport(as_of=today.isoformat())
        for task in sorted(self.store.open_tasks(), key=lambda t: t.due_date):
            days, overdue, action = self._evaluate(task, today)
            report.entries.append(
                MonitorEntry(
                    task_id=task.task_id,
                    employee_id=task.employee_id,
                    name=task.name,
                    owner=task.owner,
                    due_date=task.due_date,
                    status=task.status,
                    days_remaining=days,
                    action=action,
                    reminded=False,
                    overdue=overdue,
                )
            )
        return report

    # -- helpers -----------------------------------------------------------
    def _evaluate(self, task: OnboardingTask, today: date) -> tuple[int, bool, str]:
        due = date.fromisoformat(task.due_date)
        days = (due - today).days
        overdue = days < 0
        approaching = 0 <= days <= self.warn_days
        if overdue:
            action = "flag_overdue"
        elif approaching:
            action = "remind_owner"
        else:
            action = "monitor"
        return days, overdue, action

    def _reminder_due(self, task: OnboardingTask) -> bool:
        if not task.last_reminded_at:
            return True
        try:
            last = datetime.fromisoformat(task.last_reminded_at)
        except ValueError:
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        elapsed = (self.now_fn() - last).total_seconds()
        return elapsed >= self.reminder_interval_hours * 3600

    @staticmethod
    def _build_reminder(task: OnboardingTask, days: int, overdue: bool) -> Reminder:
        if overdue:
            message = (
                f"OVERDUE: {task.name} for {task.employee_id} was due "
                f"{task.due_date} ({abs(days)} day(s) ago) - owner {task.owner}"
            )
        else:
            message = (
                f"DUE SOON: {task.name} for {task.employee_id} is due "
                f"{task.due_date} in {days} day(s) - owner {task.owner}"
            )
        return Reminder(
            task_id=task.task_id,
            employee_id=task.employee_id,
            name=task.name,
            owner=task.owner,
            due_date=task.due_date,
            days_remaining=days,
            overdue=overdue,
            message=message,
        )


def default_monitor() -> DeadlineMonitor:
    return DeadlineMonitor()
