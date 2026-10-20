# Authentication, authorization and rate limiting

This document describes how caller identity is established, how ownership is enforced, and how
request budgets are protected (SEC-001, SEC-002, SEC-012, NFR-004, FR-040).

## Identity: JWT bearer tokens

Identity is carried by a signed JSON Web Token in the `Authorization` header:

```
Authorization: Bearer <jwt>
```

- Algorithm and secret come from config (`AUTH__JWT_SECRET`, `AUTH__JWT_ALGORITHM`, default
  `HS256`); tokens are issued by `ecommerce_support.core.security.create_access_token` and
  validated by `decode_access_token` (PyJWT, framework-free).
- Required claims: `sub` (user id), `exp` (expiry), `iss` (`ecommerce-support`). Optional `scope`
  is a space-separated string.
- The request principal is resolved in `api/dependencies.py::get_principal`:
  - **No `Authorization` header** → anonymous `GUEST` principal (`user_id is None`). Guest access
    is allowed for public endpoints (e.g. starting a chat).
  - **Present but invalid/expired/malformed token** → `401` (`WWW-Authenticate: Bearer`). An invalid
    token is never silently downgraded to guest.
- Services receive only `user_id`; identity is never read from a client-supplied header or body
  (`X-User-Id` was removed in TASK-038).

### Scopes

`require_scope("support:admin")` gates admin-only endpoints (e.g. `GET /api/v1/feedback/report`).
Missing credentials yield `401`; an authenticated caller lacking the scope gets `403`.

## Ownership (SEC-002)

Ownership is enforced in the service layer, not in prompts:

- `ConversationService.assert_access(conversation_id, user_id=...)`, `get`, `list_messages` and
  `delete` require the conversation to belong to `user_id`.
- `ChatService` refuses to continue a conversation owned by another user, and ticket/feedback
  routes assert access to the parent conversation first.
- A cross-customer request returns **`404 Not Found`** — never `403` — so resource existence is
  not leaked.

## Rate limiting

`core/ratelimit.py::SlidingWindowRateLimiter` is a dependency-free, in-process rolling-window
counter. `api/dependencies.py::enforce_chat_rate_limit` keys the budget on the authenticated user
id (falling back to the peer address for guests) and rejects over-budget requests with `429`:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 42

{"error": {"code": "rate_limited", "message": "...", "details": {"retry_after_seconds": 42}, "retryable": true}, "request_id": "..."}
```

Budget: `LIMITS__RATE_LIMIT_PER_MINUTE` (default 60 requests / 60 s).

> **Limitation:** the limiter is process-local. Running multiple instances (or a horizontally
> scaled deployment) multiplies the effective budget. Swap in a shared store (e.g. Redis) behind
> `get_rate_limiter` when scaling out.

## Error envelope

All application and validation errors share one envelope (plus the correlation id):

```json
{
  "error": {"code": "not_found", "message": "...", "details": {}, "retryable": false},
  "request_id": "req_..."
}
```

- Mappings: `authentication_error`/`token_expired` → 401, `forbidden` → 403, `not_found` → 404,
  `conflict`/`invalid_state_transition` → 409, `validation_error` → 422, `rate_limited` → 429.
- `WWW-Authenticate: Bearer` is added to 401 responses; `Retry-After` to 429 responses.
- 422 validation responses are normalized and never echo the rejected input; unexpected errors
  return a generic message (no stack traces, no secrets, no PII).

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `AUTH__JWT_SECRET` | `change-me-in-production` | HMAC signing secret (required non-default in production) |
| `AUTH__JWT_ALGORITHM` | `HS256` | JWT signing algorithm |
| `AUTH__JWT_EXPIRES_MINUTES` | `60` | Default token lifetime |
| `LIMITS__RATE_LIMIT_PER_MINUTE` | `60` | Per-client chat request budget |
