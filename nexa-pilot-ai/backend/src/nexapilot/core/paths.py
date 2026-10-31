"""Platform-appropriate application data directories."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "nexapilot"


def _default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming"
        return Path(base) / APP_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(base) / APP_DIR_NAME


def data_dir() -> Path:
    """Return the root directory for all persistent NexaPilot data."""
    override = os.environ.get("NEXAPILOT_DATA_DIR")
    if override:
        return Path(override).expanduser()
    return _default_data_dir()


def config_dir() -> Path:
    return data_dir() / "config"


def db_path() -> Path:
    return data_dir() / "nexapilot.db"


def logs_dir() -> Path:
    return data_dir() / "logs"


def workspaces_dir() -> Path:
    return data_dir() / "workspaces"


def default_workspace() -> Path:
    """The single workspace the coding agent may operate in by default."""
    return workspaces_dir() / "default"


def ensure_dirs() -> None:
    for path in (data_dir(), config_dir(), logs_dir(), workspaces_dir()):
        path.mkdir(parents=True, exist_ok=True)
