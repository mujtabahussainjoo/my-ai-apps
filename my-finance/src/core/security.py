"""Security guardrails: secret redaction, untrusted-input handling, kill switch.

This module is the single place that knows how to (a) stop secrets from
escaping into logs, prompts, or API responses, and (b) treat text that came
from outside the trust boundary — news headlines, webhook bodies, LLM tool
output — as hostile data rather than instructions.

Trust boundary rule used throughout the codebase::

    SYSTEM_PROMPT  = trusted, authored here in src/llm/prompts/
    USER_CONTENT   = untrusted, wrapped in delimiters + sanitised
    TOOL_RESULT    = untrusted, sanitised before re-entering the model
"""

from __future__ import annotations

import hmac
import json
import re
import time
from collections.abc import Iterable
from hashlib import sha256
from typing import Any, Final

from src.core.enums import TradingMode
from src.core.exceptions import LiveTradingDisabledError, PromptInjectionError

# ── Secret redaction ────────────────────────────────────────────────────────

_REDACTED: Final = "***REDACTED***"

#: Environment-variable names whose *values* must never be logged or persisted.
SENSITIVE_ENV_NAMES: Final[frozenset[str]] = frozenset(
    {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "EXCHANGE_API_KEY",
        "EXCHANGE_API_SECRET",
        "BINANCE_API_KEY",
        "BINANCE_API_SECRET",
        "POSTGRES_PASSWORD",
        "DATABASE_URL",
        "REDIS_URL",
        "TRADINGVIEW_WEBHOOK_SECRET",
        "TRADINGVIEW_SECRET",
        "MCP_ALLOW_ORDER_TOOLS",
    }
)

#: Substrings that mark a key/value pair as secret regardless of the name.
_SECRET_VALUE_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    # JSON: "api_key": "...", 'secret' => '...'
    re.compile(
        r"""(?i)(["']?\b(?:api[_-]?key|api[_-]?secret|secret[_-]?key|secret|password"""
        r"""|passwd|token|authorization|private[_-]?key|access[_-]?token|refresh[_-]?token"""
        r"""|webhook[_-]?secret|signature)\b["']?\s*[:=]\s*)(["'])([^"']{6,})\2"""
    ),
    # Bare assignments: OPENAI_API_KEY=sk-...
    re.compile(
        r"(?i)\b([A-Z][A-Z0-9_]*(?:API_KEY|API_SECRET|SECRET|PASSWORD|TOKEN)[A-Z0-9_]*)\s*=\s*"
        r"([^\s,;\"'}\s]{6,})"
    ),
    # Well-known token prefixes.
    re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}"),  # OpenAI
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{12,}"),  # Anthropic
    re.compile(r"\bghp_[A-Za-z0-9]{20,}"),  # GitHub PAT
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),  # JWT
    # Binance/Coinbase style 64-hex secrets.
    re.compile(r"(?<![A-Fa-f0-9])[A-Fa-f0-9]{48,}(?![A-Fa-f0-9])"),
)


def redact(value: Any) -> Any:
    """Recursively strip anything that looks like a secret.

    Applied automatically to every log record and to API error payloads.
    """
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                out[key] = _REDACTED
            else:
                out[key] = redact(item)
        return out
    if isinstance(value, (list, tuple)):
        rebuilt = [redact(item) for item in value]
        return type(value)(rebuilt) if isinstance(value, tuple) else rebuilt
    return value


def _is_sensitive_key(key: str) -> bool:
    upper = key.upper()
    if upper in SENSITIVE_ENV_NAMES:
        return True
    return any(
        token in upper for token in ("SECRET", "PASSWORD", "API_KEY", "TOKEN", "PRIVATE_KEY", "CREDENTIAL")
    )


def _redact_string(text: str) -> str:
    result = text
    for pattern in _SECRET_VALUE_PATTERNS:
        if pattern.groups >= 2:
            result = pattern.sub(lambda m: f"{m.group(1)}{_REDACTED}", result)
        else:
            result = pattern.sub(_REDACTED, result)
    return result


def assert_no_secrets(payload: str, *, context: str = "payload") -> None:
    """Fail loudly when a payload about to leave the process contains a secret.

    Used on prompts and on the values handed to the LLM: Workflow.md §27 says
    exchange secrets must never appear in prompts or LLM context, so this is
    the last line of defence rather than a convention we hope people follow.
    """
    for pattern in _SECRET_VALUE_PATTERNS:
        match = pattern.search(payload)
        if match:
            raise RuntimeError(
                f"Guardrail: possible secret detected in {context}. "
                "Refusing to send it to the model. Pattern matched near offset "
                f"{match.start()}. Replace it with a reference/alias."
            )


# ── Untrusted input handling ────────────────────────────────────────────────

#: Instruction-shaped phrases that must not appear in data fields. If news or a
#: webhook body contains these, the text is data describing an attack, not an
#: instruction we should obey.
_INJECTION_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"(?i)\bignore\s+(?:all\s+|any\s+)?(?:previous|prior|above|earlier)\s+"
        r"(?:instruction|instructions|prompt|prompts|rule|rules|direction|directions)"
    ),
    re.compile(r"(?i)\bdisregard\s+(?:all\s+|any\s+)?(?:previous|prior|above|earlier|system)\b"),
    re.compile(r"(?i)\byou\s+are\s+now\s+(?:a|an|in)\b.{0,40}\b(?:mode|assistant|dan|jailbreak)"),
    re.compile(
        r"(?i)\b(?:new|updated|revised)\s+(?:system\s+)?"
        r"(?:instruction|instructions|prompt|prompts)\s*[:\-]"
    ),
    re.compile(
        r"(?i)\bact\s+as\s+(?:if\s+you\s+are\s+)?(?:a|an)?\s*"
        r"(?:unrestricted|unfiltered|jailbroken|hacker)\b"
    ),
    re.compile(
        r"(?i)\b(?:reveal|print|show|output|repeat)\s+(?:me\s+)?(?:your\s+|the\s+)?"
        r"(?:system\s+prompt|instructions|api\s*key|secret|password|credentials)"
    ),
    re.compile(r"(?i)\boverride\s+(?:the\s+)?(?:risk|safety|guardrail|guardrails|limits?|rules?)"),
    re.compile(
        r"(?i)\b(?:disable|remove|turn\s+off|bypass)\s+"
        r"(?:the\s+)?(?:risk\s+engine|guardrails?|safety\s+checks?|stop[\s-]?loss)"
    ),
    re.compile(r"(?i)\b(?:send|transfer|withdraw)\s+(?:all\s+)?(?:funds|balance|balances)\b"),
    re.compile(r"(?i)<\s*/?\s*(?:system|instructions?|prompt)\s*>"),
    re.compile(r"(?i)\[\s*/?\s*(?:INST|SYSTEM)\s*\]"),
    re.compile(r"(?i)\bmax(?:imize)?\s+(?:the\s+)?(?:position|leverage)\s+to\b"),
)

#: Characters stripped from untrusted text. Data is never allowed to carry
#: template fences that could break out of its delimited block.
_UNSAFE_CHARS: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def contains_prompt_injection(text: str) -> bool:
    """True when untrusted text looks like it is trying to steer the model."""
    if not text:
        return False
    lowered = text.lower()
    return any(pattern.search(lowered) for pattern in _INJECTION_PATTERNS)


def sanitize_untrusted(
    text: str,
    *,
    max_length: int = 2000,
    field: str = "content",
) -> str:
    """Neutralise untrusted text before it enters a prompt or a log.

    - Strips control characters and template fences.
    - Collapses whitespace so a payload cannot fake structural boundaries.
    - Truncates hard so a huge body cannot blow the context budget.
    - Raises :class:`PromptInjectionError` if it detects instruction injection,
      which the caller is expected to treat as a rejection, not a retry.
    """
    if text is None:
        return ""
    if contains_prompt_injection(text):
        raise PromptInjectionError(
            f"Instruction-injection pattern detected in untrusted field '{field}'. "
            "Content dropped and the event flagged for review."
        )
    cleaned = _UNSAFE_CHARS.sub(" ", text)
    cleaned = cleaned.replace("```", "`` `")
    cleaned = re.sub(r"[<>]", lambda m: {"<": "‹", ">": "›"}[m.group(0)], cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > max_length:
        suffix = " […truncated]"
        cleaned = cleaned[: max_length - len(suffix)] + suffix
    return cleaned


def wrap_untrusted(text: str, label: str) -> str:
    """Delimit untrusted text so the model treats it as quoted data."""
    return f"<{label}>\n{text}\n</{label}>"


# ── Webhook authentication ──────────────────────────────────────────────────


def constant_time_equals(left: str, right: str) -> bool:
    """Timing-safe string comparison. Always use for secrets."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def _unwrap_secret(value: Any) -> str | None:
    """Accept either a plain string or a pydantic ``SecretStr``.

    Settings store secrets as ``SecretStr``, so a caller passing one straight
    through here would otherwise get an ``AttributeError`` at verification time
    - which surfaces as a 500 on the one route whose job is to reject bad
    input, and quietly turns "wrong secret" into "server error".
    """
    if value is None:
        return None
    getter = getattr(value, "get_secret_value", None)
    return getter() if callable(getter) else str(value)


def verify_shared_secret(provided: str | None, expected: Any) -> bool:
    expected_str = _unwrap_secret(expected)
    provided_str = _unwrap_secret(provided)
    if not expected_str or not provided_str:
        return False
    return constant_time_equals(provided_str, expected_str)


def canonical_payload_hash(body: bytes) -> str:
    """SHA-256 of the exact body bytes, for audit trails and idempotency."""
    return sha256(body).hexdigest()


def idempotency_key(namespace: str, *parts: Any) -> str:
    """Deterministic key so a retried request cannot double-execute."""
    raw = "|".join([namespace, *(str(p) for p in parts)])
    return sha256(raw.encode("utf-8")).hexdigest()[:32]


class ReplayGuard:
    """Sliding-window replay protection for webhooks and approvals.

    Webhook deliveries are retried by the provider, so we must distinguish a
    legitimate retry from an attacker replaying a captured body to force a
    duplicate order.
    """

    def __init__(self, window_seconds: int = 300) -> None:
        self._window = window_seconds
        self._seen: dict[str, float] = {}

    @property
    def window_seconds(self) -> int:
        return self._window

    def check_and_record(self, key: str, *, now: float | None = None) -> bool:
        """Return True if the key is fresh. Old keys are evicted on the way."""
        current = now if now is not None else time.time()
        self._evict(current)
        if key in self._seen:
            return False
        self._seen[key] = current
        return True

    def _evict(self, now: float) -> None:
        cutoff = now - self._window
        stale = [k for k, ts in self._seen.items() if ts < cutoff]
        for key in stale:
            del self._seen[key]

    def reset(self) -> None:
        self._seen.clear()


# ── Live-trading kill switch ────────────────────────────────────────────────


class KillSwitch:
    """Process-wide, operator-controlled circuit breaker.

    The risk engine refuses to approve *any* order while engaged. It defaults
    to armed-closed (not engaged) and can only be released by an explicit call,
    which the API exposes only to an authenticated operator endpoint.
    """

    def __init__(self) -> None:
        self._engaged = False
        self._reason: str | None = None
        self._engaged_at: float | None = None

    @property
    def engaged(self) -> bool:
        return self._engaged

    @property
    def reason(self) -> str | None:
        return self._reason

    @property
    def engaged_at(self) -> float | None:
        return self._engaged_at

    def engage(self, reason: str) -> None:
        if not self._engaged:
            self._engaged = True
            self._reason = reason
            self._engaged_at = time.time()

    def release(self, *, operator: str) -> None:
        """Release the switch. The operator identity is recorded by the caller."""
        self._engaged = False
        self._reason = None
        self._engaged_at = None

    def status(self) -> dict[str, Any]:
        return {
            "engaged": self._engaged,
            "reason": self._reason,
            "engaged_at": self._engaged_at,
        }


#: Single shared instance. Imported by the risk engine, the API, and the worker.
kill_switch = KillSwitch()


def assert_live_trading_allowed(
    mode: TradingMode,
    *,
    live_enabled: bool,
    acknowledgement: bool,
) -> None:
    """The only sanctioned gate in front of real-money execution.

    Three independent conditions must all hold. They are deliberately separate
    so a single misconfiguration cannot enable live trading:

    1. the requested mode is LIVE,
    2. ``LIVE_TRADING_ENABLED`` is set,
    3. ``LIVE_TRADING_I_UNDERSTAND_THE_RISK`` acknowledgement is set.
    """
    if mode is not TradingMode.LIVE:
        return
    if not live_enabled:
        raise LiveTradingDisabledError(
            "Live trading is disabled. Set LIVE_TRADING_ENABLED=true to enable. "
            "This is intentional: promotion from paper/testnet must be an "
            "explicit human decision."
        )
    if not acknowledgement:
        raise LiveTradingDisabledError(
            "Live trading requires LIVE_TRADING_I_UNDERSTAND_THE_RISK=true as an "
            "explicit risk acknowledgement."
        )


# ── Misc helpers ────────────────────────────────────────────────────────────


def clip_float(value: float, low: float, high: float) -> float:
    """Clamp a float into a range. Used to keep LLM output numerically sane."""
    return max(low, min(high, value))


def safe_json_dumps(payload: Any, *, limit: int = 8000) -> str:
    """Serialise to JSON after redaction, truncated to a bounded size."""
    text = json.dumps(redact(payload), default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + " […truncated]"


def redact_iterable(values: Iterable[Any]) -> list[Any]:
    return [redact(v) for v in values]
