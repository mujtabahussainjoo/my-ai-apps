"""Canonical target-system specifications.

Shared by the demo portal (route registration) and the adapters (URL
building) so the two never drift apart.
"""

from __future__ import annotations

from app.models import TargetSystem

# target value -> {"resource": path segment, "operation": operation name}
TARGET_SPECS: dict[str, dict[str, str]] = {
    TargetSystem.WORKDAY.value: {
        "resource": "employees",
        "operation": "upsert_employee",
    },
    TargetSystem.OKTA.value: {
        "resource": "provision",
        "operation": "provision_access",
    },
    TargetSystem.GOOGLE_WORKSPACE.value: {
        "resource": "accounts",
        "operation": "upsert_account",
    },
    TargetSystem.SLACK.value: {
        "resource": "access",
        "operation": "upsert_access",
    },
    TargetSystem.EQUIPMENT.value: {
        "resource": "requests",
        "operation": "upsert_request",
    },
    TargetSystem.COHORT_TRACKER.value: {
        "resource": "employees",
        "operation": "upsert_employee",
    },
}
