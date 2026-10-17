"""AI-assisted exception classification (advisory only).

The model may suggest a next action for an ambiguous exception, but it
can **never** overwrite records, bypass validation or grant access. Its
answer is validated against a strict schema and stored as a
recommendation for a human/ deterministic policy to act on.

If ``OPENAI_API_KEY`` is not configured (or the call fails), a
deterministic fallback policy is used so the workflow keeps working.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.config import settings

# Actions the model is allowed to recommend. Nothing here changes state
# on its own - "ignore"/"retry" are still subject to deterministic policy.
ALLOWED_ACTIONS = {
    "human_review",
    "request_data_correction",
    "escalate_owner",
    "retry",
    "ignore",
}

# Deterministic policy used when AI is unavailable or returns junk.
DEFAULT_ACTION_BY_TYPE: dict[str, str] = {
    "cross_system_conflict": "human_review",
    "not_approved": "human_review",
    "duplicate_employee": "human_review",
    "propagation_permanent_failure": "human_review",
    "unknown_location": "request_data_correction",
    "invalid_date": "request_data_correction",
    "incomplete_address": "request_data_correction",
    "invalid_email": "request_data_correction",
    "missing_required": "request_data_correction",
    "retry_exhausted": "escalate_owner",
}
DEFAULT_ACTION = "human_review"

_SYSTEM_PROMPT = (
    "You classify employee-onboarding integration exceptions. "
    "Respond with ONE JSON object only, no prose, with keys "
    '"exception_type" (string), "recommended_action" (one of '
    f"{sorted(ALLOWED_ACTIONS)}), and \"reason\" (short string). "
    "You are advisory: you cannot change records or access."
)


@dataclass
class ExceptionClassification:
    exception_type: str
    recommended_action: str
    reason: str
    ai_used: bool = False
    model: str | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "exception_type": self.exception_type,
            "recommended_action": self.recommended_action,
            "reason": self.reason,
            "ai_used": self.ai_used,
            "model": self.model,
            "note": self.note,
        }


class AIHelper:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        client: Any | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.api_key = settings.openai_api_key if api_key is None else api_key
        self.model = model or settings.openai_model
        self._client = client
        self.timeout = timeout
        self.last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) or self._client is not None

    def classify(
        self,
        *,
        exception_type: str,
        reason: str,
        field_name: str | None = None,
    ) -> ExceptionClassification:
        if not self.enabled:
            return self._fallback(
                exception_type, reason, ai_used=False, note="ai_disabled"
            )
        try:
            raw = self._call_model(exception_type, reason, field_name)
            return self._parse(raw, exception_type, reason)
        except Exception as exc:  # noqa: BLE001 - never let AI break the workflow
            self.last_error = f"{type(exc).__name__}: {exc}"
            return self._fallback(
                exception_type, reason, ai_used=False, note="ai_error"
            )

    # -- internals ---------------------------------------------------------
    def _client_or_create(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.api_key,
                base_url=settings.openai_base_url,
                timeout=self.timeout,
            )
        return self._client

    def _call_model(
        self, exception_type: str, reason: str, field_name: str | None
    ) -> dict[str, Any]:
        # Minimum context only: exception code, field and a short reason.
        # No names, addresses, emails or identifiers are sent.
        payload = {
            "exception_type": exception_type,
            "field_name": field_name,
            "reason": reason[:200],
        }
        client = self._client_or_create()
        response = client.chat.completions.create(
            model=self.model,
            temperature=0,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload)},
            ],
        )
        content = response.choices[0].message.content or ""
        return self._extract_json(content)

    @staticmethod
    def _extract_json(content: str) -> dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("AI response was not a JSON object")
        return data

    def _parse(
        self, raw: dict[str, Any], exception_type: str, reason: str
    ) -> ExceptionClassification:
        action = str(raw.get("recommended_action", "")).strip()
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"disallowed recommended_action: {action!r}")
        return ExceptionClassification(
            exception_type=str(raw.get("exception_type") or exception_type),
            recommended_action=action,
            reason=str(raw.get("reason") or reason)[:280],
            ai_used=True,
            model=self.model,
        )

    def _fallback(
        self,
        exception_type: str,
        reason: str,
        *,
        ai_used: bool,
        note: str,
    ) -> ExceptionClassification:
        return ExceptionClassification(
            exception_type=exception_type,
            recommended_action=DEFAULT_ACTION_BY_TYPE.get(exception_type, DEFAULT_ACTION),
            reason=reason,
            ai_used=ai_used,
            note=note,
        )


def default_ai_helper() -> AIHelper:
    return AIHelper()
