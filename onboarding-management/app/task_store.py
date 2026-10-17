"""Local store for onboarding tasks (the "cohort tracker" view).

Tasks are seeded from ``sample_events/onboarding_tasks.json`` using
relative day offsets so the demo always shows approaching and overdue
tasks, then persisted to ``data/cohort_tracker.json``.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import date, timedelta
from pathlib import Path

from app.config import BASE_DIR, settings
from app.models import CLOSED_TASK_STATUSES, OnboardingTask

DEFAULT_SEED = BASE_DIR / "sample_events" / "onboarding_tasks.json"


class TaskStore:
    def __init__(
        self,
        path: str | Path | None = None,
        seed_path: str | Path | None = None,
        today: date | None = None,
    ) -> None:
        self.path = Path(path) if path else Path(settings.tracker_path)
        self.seed_path = Path(seed_path) if seed_path else DEFAULT_SEED
        self._lock = threading.Lock()
        self._tasks: dict[str, OnboardingTask] = {}
        self._load(today or date.today())

    # -- reads -------------------------------------------------------------
    def all(self) -> list[OnboardingTask]:
        with self._lock:
            return list(self._tasks.values())

    def open_tasks(self) -> list[OnboardingTask]:
        return [t for t in self.all() if t.is_open]

    def get(self, task_id: str) -> OnboardingTask | None:
        with self._lock:
            return self._tasks.get(task_id)

    # -- writes ------------------------------------------------------------
    def update_status(self, task_id: str, status: str) -> OnboardingTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            task.status = status
            self._save_locked()
            return task

    def record_reminder(self, task_id: str, when_iso: str) -> OnboardingTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            task.last_reminded_at = when_iso
            task.reminder_history.append(when_iso)
            self._save_locked()
            return task

    def clear(self) -> None:
        with self._lock:
            self._tasks.clear()
            self._save_locked()

    def reset(self, today: date | None = None) -> None:
        """Re-seed the tracker from the sample tasks (demo reset)."""
        with self._lock:
            self._tasks = self._seed(today or date.today())
            self._save_locked()

    # -- persistence -------------------------------------------------------
    def _load(self, today: date) -> None:
        if self.path.exists():
            raw = json.loads(self.path.read_text())
            self._tasks = {
                str(k): OnboardingTask.from_dict(v) for k, v in raw.items()
            }
            return
        self._tasks = self._seed(today)
        self._save_locked()

    def _seed(self, today: date) -> dict[str, OnboardingTask]:
        if not self.seed_path.exists():
            return {}
        raw = json.loads(self.seed_path.read_text())
        tasks: dict[str, OnboardingTask] = {}
        for item in raw:
            item = dict(item)
            offset = int(item.pop("due_in_days", 0))
            item["due_date"] = (today + timedelta(days=offset)).isoformat()
            task = OnboardingTask.from_dict(item)
            tasks[task.task_id] = task
        return tasks

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: task.to_dict() for key, task in self._tasks.items()}
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str))
        os.replace(tmp, self.path)


def is_closed(status: str) -> bool:
    return status in CLOSED_TASK_STATUSES
