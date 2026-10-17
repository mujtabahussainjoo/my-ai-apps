"""Central configuration for the onboarding prototype.

Values come from environment variables (optionally loaded from a local
``.env`` file). The module deliberately has no hard dependency on the AI
provider so the deterministic workflow keeps working when OpenAI is
unavailable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _path(name: str, default: str) -> Path:
    raw = os.getenv(name) or default
    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


@dataclass(frozen=True)
class Settings:
    demo_portal_url: str = os.getenv("DEMO_PORTAL_URL", "http://127.0.0.1:8088")
    demo_portal_host: str = os.getenv("DEMO_PORTAL_HOST", "127.0.0.1")
    demo_portal_port: int = _int("DEMO_PORTAL_PORT", 8088)

    web_host: str = os.getenv("WEB_HOST", "0.0.0.0")
    web_port: int = _int("WEB_PORT", 8090)
    web_live: bool = os.getenv("WEB_LIVE", "").lower() in {"1", "true", "yes", "on"}

    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    max_retries: int = _int("MAX_RETRIES", 3)
    retry_base_delay_seconds: float = _float("RETRY_BASE_DELAY_SECONDS", 0.2)

    ledger_path: Path = _path("LEDGER_PATH", "data/idempotency_ledger.json")
    audit_path: Path = _path("AUDIT_PATH", "data/audit_log.jsonl")
    exceptions_path: Path = _path("EXCEPTIONS_PATH", "data/exceptions.json")
    tracker_path: Path = _path("TRACKER_PATH", "data/cohort_tracker.json")

    deadline_warn_days: int = _int("DEADLINE_WARN_DAYS", 7)
    reminder_interval_hours: int = _int("REMINDER_INTERVAL_HOURS", 24)

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openai_api_key)


settings = Settings()
