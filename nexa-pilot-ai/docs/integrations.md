# Integrations

All integrations are plain `httpx` adapters with timeouts, normalized errors, and test
transports. Nothing is enabled until you configure it; unconfigured capabilities raise
`not_configured` with a `setup_hint` instead of failing silently.

## Model providers

| Provider | Auth | Default model | Default base URL | Notes |
| --- | --- | --- | --- | --- |
| OpenAI | API key | `gpt-4o-mini` | `https://api.openai.com/v1` | streaming, tools, structured output |
| Anthropic Claude | API key | `claude-sonnet-4-5` | `https://api.anthropic.com/v1` | streaming + tools via Messages API |
| Google Gemini | API key | `gemini-2.0-flash` | `https://generativelanguage.googleapis.com/v1beta` | streaming + function calls |
| Ollama (local) | none | `llama3.1` | `http://127.0.0.1:11434` | no cloud key; capability detection reports missing tools/vision honestly |
| Custom OpenAI-compatible | API key or none | — | `http://127.0.0.1:8000/v1` | LM Studio, vLLM, gateways |

Exactly one provider is active. Activation runs a connection test and refuses to switch on
failure; there is no automatic fallback between providers. Secrets are stored under
`provider:<id>` references in the vault.

Capability flags (`streaming`, `tool_calling`, `structured_output`, `system_prompt`,
`vision`, `max_context_tokens`) are advertised per spec and surfaced in Settings. Models
that cannot call tools still answer chat, but workflow tools will not run.

## Web search and fetching

| Provider | Key reference | Endpoint |
| --- | --- | --- |
| Brave Search | `search:brave:api_key` | official Brave API |
| Tavily | `search:tavily:api_key` | official Tavily API |
| SearxNG | none | your `web_search_endpoint` |

`fetch_page` rejects non-HTTP(S) schemes, URL credentials, and private/link-local/metadata
addresses, re-checking each redirect. Research answers carry source URLs and a retrieval
timestamp; the prompt forbids inventing sources.

## Email

### Gmail (OAuth 2.0, PKCE)

Scopes requested: `gmail.modify` + `gmail.send` (read, draft, label, send). The client id and
secret are read from `google:oauth:client_id` / `google:oauth:client_secret`; the refresh
token is stored per connected account. Sync pulls the latest N messages and deduplicates on
the provider message id (there is no Gmail history cursor yet); expired or revoked tokens
surface as `auth_error` and the account can be reconnected.

### Generic IMAP + SMTP

Host, port, username, and password (or app password) per account. IMAP uses TLS; SMTP uses
STARTTLS. Bodies are parsed defensively (`email` package) and treated as untrusted content.

Multiple accounts stay isolated by `account_id`. Sending, forwarding, and deleting always
require approval bound to the exact recipients/subject/body shown.

## Calendar

Google Calendar (`calendar.events` scope) over the same OAuth connection. Events store
provider id, calendar id, account id, and provenance. Sync deduplicates on a stable
`dedupe_key` (`gcal:<event id>`), preserves IANA time zones, and supports reminders. Local
event creation is approval-gated; extracted events from email are proposals until accepted.

## Travel

| Provider | Key references | Coverage |
| --- | --- | --- |
| Amadeus | `travel:amadeus:api_key`, `travel:amadeus:api_secret` | flights, hotels; prices/fees as returned with timestamps |
| Rail guidance | none | official portal links + guidance; no scraping, no fabricated fares |

NexaPilot does **not** complete bookings or take payments. Search results include booking
links and explicitly state availability/price limitations. Any “book” request is answered
with guidance plus the official link.

## Finance

| Piece | Details |
| --- | --- |
| Quotes | Stooq (CSV) or Yahoo (chart JSON), timestamped; delayed-data caveat is included |
| Portfolio | local positions/watchlist; values marked with quote timestamp |
| Paper orders | stored locally with the fill price at submission; no broker call |
| Live orders | generic REST broker (`finance_broker_base_url`, `finance_broker_api_key_ref`), approval-gated, capped by `finance_max_order_value` and `finance_max_order_quantity` |

No order is ever reported as filled without a provider confirmation payload. Ambiguous
responses are reported as `unknown` and require checking the broker.

## Local runtime

- **Ollama**: install from <https://ollama.com>, run `ollama serve`, `ollama pull llama3.1`,
  then select Ollama in Settings. Connection tests report whether the host is reachable and
  whether the model exists.
- **Coding workspace**: set `coding_workspace_root` (Settings → Coding). Without it, file and
  command tools are not offered at all.
