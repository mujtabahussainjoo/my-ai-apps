"""Persisted overrides for user-editable settings.

Environment variables and defaults live in :class:`Settings`. Anything the user
changes in the UI is written to ``config/settings.json`` so it survives a
restart, and is re-applied on top of the environment-derived values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from nexapilot.core.config import Settings
from nexapilot.core.logging import get_logger
from nexapilot.core.paths import config_dir

log = get_logger(__name__)

MUTABLE_SETTINGS: frozenset[str] = frozenset(
    {
        "coding_workspace_root",
        "web_search_provider",
        "web_search_endpoint",
        "travel_provider",
        "travel_api_base_url",
        "finance_provider",
        "finance_broker_base_url",
        "finance_broker_api_key_ref",
        "secret_backend",
        "log_level",
    }
)


def overrides_path() -> Path:
    return config_dir() / "settings.json"


def load_overrides() -> dict[str, Any]:
    path = overrides_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("settings.overrides_unreadable", path=str(path))
        return {}
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if key in MUTABLE_SETTINGS}


def save_overrides(updates: dict[str, Any]) -> dict[str, Any]:
    current = load_overrides()
    current.update({key: value for key, value in updates.items() if key in MUTABLE_SETTINGS})
    path = overrides_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2, sort_keys=True), "utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)
    return current


def apply_overrides(settings: Settings, overrides: dict[str, Any] | None = None) -> Settings:
    values = dict(overrides if overrides is not None else load_overrides())
    if not values:
        return settings
    merged = {**settings.model_dump(), **values}
    try:
        return Settings.model_validate(merged)
    except Exception:
        log.warning("settings.overrides_invalid", keys=sorted(values))
        return settings
