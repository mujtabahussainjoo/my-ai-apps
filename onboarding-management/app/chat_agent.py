"""Read-only "onboarding copilot" agent for the dashboard chat.

The agent answers operator questions about the current workflow state:
open exceptions, recent audit entries, onboarding tasks and the operation
ledger. It is strictly **advisory and read-only** - it can look at state
but can never propagate a change, resolve an exception, bypass validation
or grant access.

Like :class:`app.ai_helper.AIHelper`, it degrades gracefully: if no
``OPENAI_API_KEY`` is configured (or the call fails) a deterministic,
keyword-based responder answers from the same context so the feature
keeps working offline.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.config import settings

# Safety net: the agent never sends more than this many characters of the
# compact context to the model.
_MAX_CONTEXT_CHARS = 6000
_MAX_HISTORY_TURNS = 6

_SYSTEM_PROMPT = (
    "You are the BetterUp Onboarding Copilot, an assistant embedded in a "
    "read-only operations dashboard. You answer questions about the current "
    "employee-onboarding workflow: open exceptions, the audit trail, "
    "onboarding tasks/deadlines and the idempotency operation ledger. "
    "Ground every answer ONLY in the JSON context provided; if something is "
    "not in the context, say you don't have that information. Be concise and "
    "practical (a few sentences or a short list). You are advisory and "
    "read-only: never claim to change records, resolve exceptions, retry "
    "operations or bypass validation. Never reveal credentials or secrets."
)

# Deterministic fallback intents -> keywords used to score a question.
_INTENTS: dict[str, tuple[str, ...]] = {
    "exceptions": (
        "exception",
        "exceptions",
        "review",
        "blocked",
        "block",
        "conflict",
        "mismatch",
        "needs_review",
    ),
    "deadlines": (
        "deadline",
        "overdue",
        "due",
        "task",
        "tasks",
        "reminder",
        "hardware",
        "background",
        "okta provisioning",
    ),
    "failures": (
        "fail",
        "failed",
        "failure",
        "retry",
        "partial",
        "pending",
        "timeout",
        "ledger",
        "idempot",
        "duplicate",
        "skipped",
    ),
    "audit": (
        "audit",
        "history",
        "log",
        "changed",
        "change",
        "what happened",
        "timeline",
    ),
}


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class ChatResponse:
    reply: str
    ai_used: bool = False
    model: str | None = None
    note: str = ""
    intent: str = "general"
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reply": self.reply,
            "ai_used": self.ai_used,
            "model": self.model,
            "note": self.note,
            "intent": self.intent,
            "sources": self.sources,
        }


class ChatAgent:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        client: Any | None = None,
        timeout: float = 20.0,
        max_context_chars: int = _MAX_CONTEXT_CHARS,
    ) -> None:
        self.api_key = settings.openai_api_key if api_key is None else api_key
        self.model = model or settings.openai_model
        self._client = client
        self.timeout = timeout
        self.max_context_chars = max_context_chars
        self.last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key) or self._client is not None

    # -- public API --------------------------------------------------------
    def respond(
        self,
        message: str,
        *,
        snapshot: dict[str, Any],
        history: list[ChatMessage] | None = None,
    ) -> ChatResponse:
        message = (message or "").strip()
        if not message:
            return ChatResponse(
                reply="Ask me about open exceptions, onboarding deadlines, "
                "recent audit changes or the operation ledger.",
                note="empty_message",
            )

        if self.enabled:
            try:
                reply = self._ask_model(message, snapshot, history or [])
                return ChatResponse(
                    reply=reply,
                    ai_used=True,
                    model=self.model,
                    intent=self._detect_intent(message),
                    sources=self._used_sources(snapshot),
                )
            except Exception as exc:  # noqa: BLE001 - never break the dashboard
                self.last_error = f"{type(exc).__name__}: {exc}"

        return self._fallback(message, snapshot, note=(
            "ai_disabled" if not self.enabled else "ai_error"
        ))

    # -- model path --------------------------------------------------------
    def _client_or_create(self) -> Any:
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.api_key,
                base_url=settings.openai_base_url,
                timeout=self.timeout,
            )
        return self._client

    def _ask_model(
        self,
        message: str,
        snapshot: dict[str, Any],
        history: list[ChatMessage],
    ) -> str:
        context = self._compact_context(snapshot)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "system",
                "content": "Current workflow context (JSON):\n" + context,
            },
        ]
        for turn in history[-_MAX_HISTORY_TURNS:]:
            if turn.role in ("user", "assistant") and turn.content:
                messages.append(
                    {"role": turn.role, "content": turn.content[:1000]}
                )
        messages.append({"role": "user", "content": message[:2000]})

        response = self._client_or_create().chat.completions.create(
            model=self.model,
            temperature=0,
            messages=messages,
        )
        return (response.choices[0].message.content or "").strip() or (
            "I couldn't find an answer in the current context."
        )

    def _compact_context(self, snapshot: dict[str, Any]) -> str:
        """Serialize a minimal, size-bounded view of the workflow state."""
        view = {
            "summary": snapshot.get("summary", {}),
            "open_exceptions": snapshot.get("open_exceptions", [])[:20],
            "recent_audit": snapshot.get("recent_audit", [])[:10],
            "tasks": snapshot.get("tasks", [])[:20],
            "monitor": snapshot.get("monitor", {}),
            "ledger": snapshot.get("ledger", [])[:20],
        }
        text = json.dumps(view, default=str, separators=(",", ":"))
        return text[: self.max_context_chars]

    # -- deterministic fallback -------------------------------------------
    def _fallback(
        self, message: str, snapshot: dict[str, Any], *, note: str
    ) -> ChatResponse:
        intent = self._detect_intent(message)
        sources = self._used_sources(snapshot)
        lines: list[str] = []

        if intent == "exceptions":
            lines.append(self._describe_exceptions(snapshot))
        elif intent == "deadlines":
            lines.extend(self._describe_deadlines(snapshot))
        elif intent == "failures":
            lines.extend(self._describe_failures(snapshot))
        elif intent == "audit":
            lines.extend(self._describe_audit(snapshot))
        else:
            lines.append(self._describe_overview(snapshot))

        return ChatResponse(
            reply="\n".join(line for line in lines if line),
            ai_used=False,
            model=None,
            note=note,
            intent=intent,
            sources=sources,
        )

    @staticmethod
    def _detect_intent(message: str) -> str:
        text = message.lower()
        best, best_score = "general", 0
        for intent, keywords in _INTENTS.items():
            score = sum(1 for kw in keywords if kw in text)
            if score > best_score:
                best, best_score = intent, score
        return best

    @staticmethod
    def _used_sources(snapshot: dict[str, Any]) -> list[str]:
        keys = (
            "summary",
            "open_exceptions",
            "recent_audit",
            "tasks",
            "monitor",
            "ledger",
        )
        return [k for k in keys if snapshot.get(k)]

    def _describe_overview(self, snapshot: dict[str, Any]) -> str:
        summary = snapshot.get("summary", {})
        return (
            "I'm the read-only Onboarding Copilot. Current state: "
            f"{summary.get('open_exceptions', 0)} open exception(s), "
            f"{summary.get('overdue_tasks', 0)} overdue task(s), "
            f"{summary.get('approaching_tasks', 0)} task(s) due soon, and "
            f"{summary.get('failed_operations', 0)} failed operation(s) in the "
            "ledger. Ask me about exceptions, deadlines, failures or the audit "
            "trail."
        )

    def _describe_exceptions(self, snapshot: dict[str, Any]) -> str:
        rows = snapshot.get("open_exceptions") or []
        if not rows:
            return "There are no open exceptions right now."
        lines = [f"{len(rows)} open exception(s):"]
        for row in rows[:10]:
            field = row.get("field_name") or "-"
            lines.append(
                f"- {row.get('exception_id')} [{row.get('exception_type')}] "
                f"employee={row.get('employee_id')} field={field} "
                f"action={row.get('recommended_action')} "
                f"ai_used={row.get('ai_used')}: {row.get('reason')}"
            )
        return "\n".join(lines)

    def _describe_deadlines(self, snapshot: dict[str, Any]) -> list[str]:
        tasks = snapshot.get("tasks") or []
        monitor = snapshot.get("monitor") or {}
        if not tasks:
            return ["There are no onboarding tasks tracked."]
        lines = [
            f"Tasks: {monitor.get('approaching', 0)} approaching, "
            f"{monitor.get('overdue', 0)} overdue."
        ]
        for entry in monitor.get("entries", [])[:10]:
            lines.append(
                f"- {entry.get('name')} ({entry.get('employee_id')}) due "
                f"{entry.get('due_date')} [{entry.get('status')}] "
                f"days_remaining={entry.get('days_remaining')} "
                f"owner={entry.get('owner')} -> {entry.get('action')}"
            )
        return lines

    def _describe_failures(self, snapshot: dict[str, Any]) -> list[str]:
        summary = snapshot.get("summary", {})
        ledger = snapshot.get("ledger") or []
        lines = [
            f"Ledger: {summary.get('failed_operations', 0)} failed, "
            f"{summary.get('skipped_operations', 0)} skipped (idempotent), "
            f"{summary.get('successful_operations', 0)} successful."
        ]
        problems = [
            op
            for op in ledger
            if op.get("status") not in ("SUCCESS", "SKIPPED_IDEMPOTENT")
        ]
        for op in problems[:10]:
            lines.append(
                f"- {op.get('target')}/{op.get('operation')} "
                f"employee={op.get('employee_id')} status={op.get('status')} "
                f"attempts={op.get('attempts')} error={op.get('last_error')}"
            )
        if not problems:
            lines.append("No failed operations in the ledger.")
        return lines

    def _describe_audit(self, snapshot: dict[str, Any]) -> list[str]:
        entries = snapshot.get("recent_audit") or []
        if not entries:
            return ["The audit trail is empty."]
        lines = [f"Last {len(entries)} audit entries (newest first):"]
        for entry in entries[:10]:
            if entry.get("entry_type") == "exception":
                lines.append(
                    f"- [exception] {entry.get('exception_id')} "
                    f"{entry.get('action')} by {entry.get('resolved_by')}"
                )
            else:
                changes = entry.get("changes") or {}
                summary = ", ".join(
                    f"{k}: {v.get('previous')} -> {v.get('new')}"
                    for k, v in list(changes.items())[:4]
                )
                lines.append(
                    f"- [{entry.get('overall_status')}] "
                    f"{entry.get('employee_id')} event={entry.get('event_id')} "
                    f"changed={', '.join(entry.get('changed_fields', [])) or '-'}"
                    + (f" ({summary})" if summary else "")
                )
        return lines


def default_chat_agent() -> ChatAgent:
    return ChatAgent()
