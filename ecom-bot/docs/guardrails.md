# Guardrail layer

Security is enforced in code, not prompts. The `guardrails/` package is framework-free and runs
at the boundaries where untrusted data enters or sensitive data could leave (FR-032, SEC-003/004/005/009).

| Module | Responsibility | Requirement |
| --- | --- | --- |
| `prompt_injection.py` | Weighted heuristic scoring of instruction-override / exfiltration / role-spoof patterns | FR-032, SEC-003 |
| `input_validation.py` | `screen_input`: size limits (DoS control) + injection block/flag | SEC-009, FR-032 |
| `output_validation.py` | `screen_output`: redact secrets/PII from outbound answers | SEC-004, SEC-005 |
| `pii.py` | `detect_pii` (kinds only) / `redact_pii`; shares patterns with `redaction.py` | SEC-005, FR-051 |
| `redaction.py` | Pattern-based masking of email/card/SSN/IP/phone/credentials | SEC-005, FR-051 |
| `authorization.py` | `require_authenticated` / `require_scope` / `require_ownership` policies | SEC-002, SEC-008, FR-040 |

## Decisions

All screens return a single `GuardrailDecision` (`allow` / `redact` / `block`) with a
machine-readable `code`, `reason`, `matches`, and — for redaction — the sanitized `text`. Callers
apply the decision rather than interpreting booleans.

- **Input** (`ChatService._run_turn`): `screen_input` blocks over-length messages (`input_too_long`)
  and prompt-injection attempts (`prompt_injection`); a blocked input is answered with the refusal
  message, the graph is not run, and a `guardrail.input_blocked` security event is logged.
- **Retrieved evidence**: treated as untrusted data and delimited/dropped above threshold in
  `rag/generation.py` (SEC-003).
- **Output** (`ChatService._screen_answer`): `screen_output` redacts secrets/payment/PII before the
  answer is persisted or streamed; redaction is logged (`guardrail.output_redacted`) with kinds only.
- **Ticket payloads**: additionally scrubbed via `redact_text` in the Jira/ServiceNow adapters
  (FR-051).

## Authorization policies

`require_authenticated` → `401`, `require_scope` → `403` (or `401` when anonymous),
`require_ownership` → `404` on mismatch (so another party's resource existence is not leaked).
These are reused by the API dependencies, services, and tools so the rule lives in one place.

## Configuration

`GUARDRAILS__ENABLED`, `GUARDRAILS__PROMPT_INJECTION_ACTION` (`block`/`flag`),
`GUARDRAILS__MAX_PROMPT_INJECTION_SCORE`, `GUARDRAILS__REDACT_PII_IN_LOGS`,
`GUARDRAILS__REDACT_PII_IN_TICKETS`, and `LIMITS__MAX_MESSAGE_CHARS`.

## Limitations

- Prompt-injection detection is heuristic (pattern-based), not a model classifier; it is one layer
  of defense, never the security boundary.
- Redaction is intentionally aggressive and pattern-based: novel PII shapes, free-form names, and
  obfuscated secrets may not be caught; structural controls (ownership checks, typed tools) remain
  the primary defenses.
