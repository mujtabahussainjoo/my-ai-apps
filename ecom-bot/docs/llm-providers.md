# LLM Providers (Phase 4)

Provider-independent LLM layer (`src/ecommerce_support/llm/`). Agents and tools talk only to
the `LLMClient` interface and provider-neutral types; no provider SDK is imported outside
`llm/providers/`.

## Selecting a provider (config only)

Exactly one provider is enabled per role, chosen in `config/llm.yaml` and overridable by env
vars. Nothing in code hard-codes a vendor; switching providers is a configuration change.

| Config key | Env var | Purpose |
| --- | --- | --- |
| `llm.provider` | `LLM__PROVIDER` | Generation/main model provider |
| `llm.model` | `LLM__MODEL` | Model id for the generation role |
| `llm.router_provider` | `LLM__ROUTER_PROVIDER` | Router role provider (falls back to `provider`) |
| `llm.router_model` | `LLM__ROUTER_MODEL` | Router model id (falls back to `model`) |
| `llm.anthropic_api_key` | `LLM__ANTHROPIC_API_KEY` | Anthropic credentials |
| `llm.openai_api_key` | `LLM__OPENAI_API_KEY` | OpenAI credentials |
| `llm.google_api_key` | `LLM__GOOGLE_API_KEY` | Gemini credentials |
| `llm.openai_base_url` | `LLM__OPENAI_BASE_URL` | OpenAI-compatible base URL (optional) |
| `llm.openai_compatible_base_url` | `LLM__OPENAI_COMPATIBLE_BASE_URL` | Third-party OpenAI-compatible endpoint (required for that provider) |
| `llm.openai_compatible_model` | `LLM__OPENAI_COMPATIBLE_MODEL` | Model id for the compatible endpoint |
| `llm.ollama_base_url` | `LLM__OLLAMA_BASE_URL` | Ollama server URL |
| `llm.timeout_seconds` | `LLM__TIMEOUT_SECONDS` | Per-call timeout (non-streaming) |
| `llm.max_retries` | `LLM__MAX_RETRIES` | Total attempt budget (3 = one call + up to 2 retries) |
| `llm.retry_backoff_base_seconds` | `LLM__RETRY_BACKOFF_BASE_SECONDS` | Backoff base (doubles per attempt) |
| `llm.retry_backoff_max_seconds` | `LLM__RETRY_BACKOFF_MAX_SECONDS` | Backoff cap |

`create_llm_client(config, role="generation"|"router")` builds the client. A provider that
needs credentials or a base URL and does not have one fails loudly with `ConfigurationError`
rather than degrading to a mock. The returned client is a `RetryingLLMClient` decorator that
applies the configured per-call timeout, bounded retry/backoff, and token/cost tracking (see
"Retries, timeouts, and usage tracking"); `client.unwrap()` reaches the raw provider adapter.
Provider switching stays a pure config change — verified by factory tests that select every
provider (including `LLM_PROVIDER=mock`) with zero credentials.

## Capability matrix

Capabilities live in `llm/capabilities.py`. Adapters declare
`capabilities = capabilities_for("<provider>")`; every method calls `require(...)` before
doing work, so an unsupported feature raises `LLMCapabilityError` and never silently degrades.

| Provider | complete | stream | structured | tool_calling | vision |
| --- | --- | --- | --- | --- | --- |
| `mock` | yes | yes | yes | yes | no |
| `anthropic` | yes | yes | yes | yes | no |
| `openai` | yes | yes | yes | yes | no |
| `gemini` | yes | yes | yes | yes | no |
| `ollama` | yes | yes | **no** | yes | no |
| `openai_compatible` | yes | yes | **no** | yes | no |

Notes:

- **`vision` is not declared by any provider.** The `LLMClient` interface has no image input
  support, so claiming it would be a lie. Adding vision is an interface change plus per-provider
  work, not a flag flip; until then `require(LLMCapability.vision)` fails loudly everywhere.
- **`ollama` and `openai_compatible` do not declare `structured`.** JSON-mode/`response_schema`
  behavior is not uniform across every server behind those APIs, so the layer refuses rather than
  returning unvalidated text. Use `tool_calling` (which is supported) or route structured needs to
  a provider that declares `structured`.

## Per-provider notes

- **mock** — deterministic, offline, scriptable queues; used for unit tests and as the default
  when nothing is configured.
- **anthropic** — Messages API via the `anthropic` SDK. `structured` is implemented by forcing a
  single `emit_structured_output` tool call and parsing its payload.
- **openai** — Chat Completions via the `openai` SDK. `structured` uses the SDK's
  `chat.completions.parse` with a Pydantic model; streaming enables `include_usage`.
- **openai_compatible** — subclasses the OpenAI adapter. Requires a `base_url`; `api_key` falls
  back to `"not-needed"` for servers that ignore auth. Inherits OpenAI behavior but only claims
  `complete`/`stream`/`tool_calling`.
- **gemini** — `google-genai` native SDK. `system_instruction` carries system messages;
  `structured` sets `response_mime_type="application/json"` with a `response_schema`;
  tools map to `function_declarations` with `ANY`/`AUTO`/`NONE` calling modes.
- **ollama** — plain `httpx` against `/api/chat` with NDJSON streaming; no API key required.

## Errors

`llm/errors.py` exposes `normalize_error(provider, error) -> LLMError`. It classifies by HTTP
status (when present, and status wins over class name) then by exception class name, producing the
app's typed errors:

| Condition | Result | Retryable |
| --- | --- | --- |
| 401/403, `AuthenticationError`-like | `LLMAuthError` | no |
| 429, `RateLimitError`-like | `LLMRateLimitError` | yes |
| 408/504, `TimeoutError`-like | `LLMTimeoutError` | yes |
| connection/unavailable | `LLMError` | yes |
| other 5xx | `LLMError` | yes |
| other 4xx | `LLMError` | no |
| unknown | `LLMError` | yes |

Messages are generic (no provider text, no secrets); `details` records `provider`, `error_type`,
and `status_code` when available.

## Retries, timeouts, and usage tracking (TASK-015)

`llm/retry.py` is the single place retry policy lives. Providers keep `max_retries=0` on their
SDK clients so the SDK never double-retries; `RetryingLLMClient` (returned by
`create_llm_client`) owns it.

- **Bounded retries.** `RetryPolicy` defaults to `max_attempts=3` (the total budget, mapped from
  `llm.max_retries`), exponential backoff `base * 2**(attempt-1)` with ±`jitter` and a
  `max_seconds` cap. `is_retryable` retries **only** transient failures — timeout, 429, 5xx,
  unreachable — and never auth or capability errors. Non-`LLMError` exceptions (programmer
  errors) propagate immediately without retry.
- **Per-call timeouts.** Each non-streaming attempt runs inside `asyncio.timeout(seconds)`; an
  expiry is normalized to `LLMTimeoutError` and is itself retryable.
- **Streaming is not retried.** A partially-consumed stream cannot be replayed, so `astream`
  passes through to the provider without retry or timeout. Usage from the terminal chunk is still
  recorded. Callers that need retries on streams should retry the whole operation.
- **Usage tracking.** `llm/usage.py` `UsageTracker` accumulates tokens and an estimated USD cost
  per call (from a static price table in `MODEL_PRICING` — estimates only, not billing). The
  factory wires the process-wide tracker automatically; `complete`/`tool_call` record on success
  and `astream` records the terminal chunk's usage. `structured()` returns only the parsed model
  (no `Usage` in its contract), so it records nothing — use `complete`/`tool_call` when usage
  must be tracked.
