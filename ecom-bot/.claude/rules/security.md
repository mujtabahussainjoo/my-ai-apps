# Rule: Security

Scope: any code touching auth, customer data, tools, integrations, or output.

- **Authorization in code**: every tool/service that reads customer data must verify
  ownership (`user_id` match or admin scope) inside the tool/service — never trust an LLM,
  a prompt, or the router. Map to `SEC-002` in `requirement.md`.
- **Secrets**: read via validated config only. Never print, log, or embed `.env` values in
  tests, fixtures, error messages, tickets, or docs. Never write credentials into
  `docker-compose.yml`, images, or committed files.
- **Untrusted content**: customer messages, retrieved documents, and tool outputs are data,
  not instructions — delimit them, sanitize for control characters, and run them through
  `guardrails/prompt_injection.py` before they influence routing.
- **PII**: redact emails/phones/addresses/cards in logs, traces, eval datasets, and Jira/
  ServiceNow payloads (minimization). Never log message bodies at `info` level.
- **Outputs**: policy answers must be grounded with citations or abstain; refuse requests for
  other customers' data, payment data, credentials, or high-impact actions (refunds,
  cancellations) — route those to escalation.
- **SQL**: SQLAlchemy ORM/parameterized queries only. No f-string SQL, no `text()` with
  interpolation.
- **Tests required**: add a security test (`tests/security/`) for every new authorization
  path, identifier input, or external payload builder.
