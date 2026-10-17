"""Catalog of the systems involved in the onboarding workflow.

Mirrors the "Systems and their typical responsibilities" table in the
brief so the UI, adapters and orchestrator all use the same real names
and roles. Target systems are derived from :data:`app.targets.TARGET_SPECS`
so resource/operation names never drift.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.targets import TARGET_SPECS

# key -> (display name, role)
_TARGET_META: dict[str, tuple[str, str]] = {
    "workday": ("Workday", "Official employee and employment records"),
    "okta": ("Okta / Lumos", "Identity, access and provisioning workflows"),
    "google_workspace": (
        "Google Workspace",
        "Company email and productivity accounts",
    ),
    "slack": ("Slack", "Employee communication and workspace access"),
    "equipment": ("Equipment / ExpoIT", "Hardware requests and delivery details"),
    "cohort_tracker": (
        "Onboarding cohort tracker",
        "Task status, dates and onboarding progress",
    ),
}


@dataclass(frozen=True)
class SystemInfo:
    key: str
    display_name: str
    kind: str  # "source" | "target" | "ai" | "orchestrator"
    role: str
    resource: str | None = None
    operation: str | None = None
    note: str = ""


def _build_catalog() -> list[SystemInfo]:
    catalog: list[SystemInfo] = [
        SystemInfo(
            key="ashby",
            display_name="Ashby",
            kind="source",
            role="Recruiting and candidate/offer information",
            note="Event source. Hires and changes start here or from approved intake.",
        )
    ]
    for key, spec in TARGET_SPECS.items():
        name, role = _TARGET_META.get(key, (key, ""))
        catalog.append(
            SystemInfo(
                key=key,
                display_name=name,
                kind="target",
                role=role,
                resource=spec["resource"],
                operation=spec["operation"],
            )
        )
    catalog.extend(
        [
            SystemInfo(
                key="ai",
                display_name="AI copilot",
                kind="ai",
                role="Exception classification and read-only operator assistance",
                note="Advisory only: recommends an action, never changes records.",
            ),
            SystemInfo(
                key="n8n_zapier",
                display_name="n8n / Zapier",
                kind="orchestrator",
                role="Optional existing workflow-orchestration tools",
                note="Not used in the prototype - this workflow orchestrates itself.",
            ),
        ]
    )
    return catalog


SYSTEM_CATALOG: list[SystemInfo] = _build_catalog()

SYSTEMS_BY_KEY: dict[str, SystemInfo] = {s.key: s for s in SYSTEM_CATALOG}

DISPLAY_NAMES: dict[str, str] = {
    s.key: s.display_name for s in SYSTEM_CATALOG
}


def display_name(key: str) -> str:
    return DISPLAY_NAMES.get(key, key)
