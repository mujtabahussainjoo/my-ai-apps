# Security

## Trust boundaries

1. **Webview → local API.** The API can act on the user's behalf, so it binds to
   `127.0.0.1` only. `NEXAPILOT_API_TOKEN` enables a constant-time bearer check on every
   route except `/api/health` and the OpenAPI/docs pages. CORS allows only the Vite dev
   origins and the Tauri webview origins (`tauri://localhost`,
   `http://tauri.localhost`, `https://tauri.localhost`). CORS preflights are exempt from
   the bearer check.
2. **Provider output → agent.** Model output is untrusted. Tool arguments are validated
   with Pydantic (`parse_arguments`) before the approval prompt is shown and again before
   execution. The router is deterministic, so the model cannot choose a different workflow.
3. **Email/calendar/web content → prompts.** These are labelled as untrusted data in the
   prompt and cannot escalate permissions; permissions are computed from configuration and
   connected accounts, never from model claims.
4. **Agent → side effects.** Side-effecting tools require a pending approval record whose
   payload is the exact `{tool, arguments}` pair. Approval is single-use.

## Permissions

Permissions are strings attached to tool specs; `RunContext.granted_permissions` is derived
from settings and connected accounts:

| Permission | Granted when |
| --- | --- |
| `web:search` | `web_search_provider` is configured |
| `fs:read`, `fs:write`, `shell:exec` | `coding_workspace_root` is set |
| `email:read/modify/send` | a Gmail or IMAP account is connected |
| `calendar:read/write` | a Google Calendar or Gmail account is connected |
| `travel:search` | `travel_provider` is configured |
| `finance:read`, `finance:trade` | always; live orders additionally require a configured broker (`finance_broker_base_url` + key) and are capped by `finance_max_order_value` / `finance_max_order_quantity` |

Tools whose permissions are not granted are not even advertised to the model.

## Approval gates (enforced in code)

| Action | Tool | Approval action |
| --- | --- | --- |
| Send / forward email | `send_email`, `forward_email` | `email.send`, `email.forward` |
| Delete email | `delete_email` | `email.delete` |
| Create calendar event | `create_event` | `calendar.create_event` |
| Place an order | `place_order` | `finance.place_order` |

`write_file` and `run_tests` are deliberately **not** approval-gated: they are confined to
the configured workspace and an allowlist of developer commands (no shell, no `git push`,
no `-exec`, scrubbed environment). Anything outside those bounds is rejected, not approved.

Approval records store action, target, risk, cost, consequences, and the redacted argument
payload. Approving does not authorise a later call with different arguments; a new request
is created. A pending approval re-surfaces instead of silently re-running.

## Secrets

- `SecretStore` abstraction: OS keyring (`keyring`), `0600` JSON file, or in-memory.
- Startup probes the keyring with a throwaway entry. If unavailable (headless Linux, CI),
  the backend falls back to the file store and reports `security: "degraded"` with an
  explanatory note in `GET /api/settings`. It never silently claims vault protection.
- Secrets are referenced by name (`google:oauth:client_secret`, `search:brave:api_key`, …),
  never returned by the API; `GET /api/settings/secrets` returns names/labels/configured
  booleans only. The `KNOWN_SECRETS` allowlist rejects arbitrary names.
- Database rows hold references only; tests assert the raw key never appears in the DB.

## SSRF and sandboxing

- `integrations/fetch.py` allows only `http`/`https`, rejects credentials in URLs, resolves
  the host, and blocks loopback/private/link-local/multicast/metadata ranges on every
  redirect hop.
- Coding tools resolve paths and reject anything that escapes the workspace, including
  symlink traversal. Commands run without a shell, with `cwd` pinned to the workspace,
  scrubbed environment, output caps, and timeouts.
- Python/Node inline evaluation flags (`-c`, `-m`, `-e`) and git history-rewriting or
  network subcommands are rejected.

## Audit

`services/audit.py` appends to `audit_log` on approval decisions and tool executions
(action, target, status, permissions, side-effect flag). Argument values, bodies, tokens,
and payment data are never recorded; a test asserts a message body and recipient address do
not appear in audit details.

## Threat model (abridged)

| Threat | Mitigation |
| --- | --- |
| Malicious page/email prompt injection | untrusted-content framing + code-enforced permissions + approvals |
| Approval replay against a different target | payload-bound approvals, single-use, exact argument match |
| Secret exfiltration via tool output | no secret access from tools; env scrubbed; errors never echo credentials |
| Local malware/other user on the machine | loopback binding, optional bearer token, OS-vault storage, `0600` fallback |
| Runaway agent loop / cost blowup | iteration and step caps, provider timeouts, retries, output truncation |
| Path traversal / symlink escape | resolve + containment checks on every file access |
| SSRF to cloud metadata | private/link-local/metadata block list with redirect re-validation |
| Destructive commands | allowlist, no shell, forbidden flags, separate confirmation path via approvals |

Known limitations: the local API is not a multi-user boundary; a process running as the same
OS user can read the SQLite database and (in degraded mode) the secret file. Installer
signing and reproducible builds are not yet implemented.
