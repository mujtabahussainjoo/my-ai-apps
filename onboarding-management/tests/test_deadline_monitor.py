"""Deadline monitoring: approaching/overdue reminders with no duplicates."""

from datetime import date, datetime, timedelta, timezone

from app.deadline_monitor import DeadlineMonitor, RecordingNotifier
from app.task_store import TaskStore

TODAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


def _monitor(tmp_path):
    store = TaskStore(path=tmp_path / "tasks.json", today=TODAY)
    notifier = RecordingNotifier()
    monitor = DeadlineMonitor(
        store=store,
        notifier=notifier,
        now_fn=lambda: NOW,
        warn_days=7,
        reminder_interval_hours=24,
    )
    return store, notifier, monitor


def test_flags_approaching_and_overdue(tmp_path):
    _store, notifier, monitor = _monitor(tmp_path)

    report = monitor.run()

    assert report.approaching == 2
    assert report.overdue == 1
    assert report.reminders_sent == 3
    actions = {e.name: e.action for e in report.entries}
    assert actions["Okta provisioning"] == "flag_overdue"
    assert actions["Background check"] == "remind_owner"
    # Completed task is not monitored.
    assert "IT hardware form" in actions
    assert len(report.entries) == 3


def test_no_duplicate_reminders_same_day(tmp_path):
    _store, notifier, monitor = _monitor(tmp_path)

    monitor.run()
    second = monitor.run()

    assert second.reminders_sent == 0
    assert len(notifier.sent) == 3


def test_reminder_repeats_after_cadence(tmp_path):
    _store, notifier, monitor = _monitor(tmp_path)
    monitor.run()

    monitor.now_fn = lambda: NOW + timedelta(days=1)
    report = monitor.run(as_of=TODAY + timedelta(days=1))

    assert report.reminders_sent == 3
    assert len(notifier.sent) == 6
