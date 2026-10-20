# Deployment

How to build, configure, and run the E-commerce AI Support Assistant with Docker.

## Artifacts

| File | Purpose |
| --- | --- |
| `Dockerfile` | Multi-stage build (uv → `python:3.12-slim`), non-root user `ecombot` (uid 10001), HTTP healthcheck on `/health`, runs `uvicorn ecommerce_support.main:app` on port 8000 |
| `docker-compose.yml` | Local/dev stack: `db` (Postgres 16 + pgvector, host port **5434**) + `api` (host port **8010**); mock LLM/ticketing defaults, dev-only JWT secret |
| `.dockerignore` | Keeps `.env`, caches, tests, and docs out of the image; only `README.md` ships (hatchling build requirement) |
| `.env.example` | Full environment template (`.env` file / `SECTION__FIELD` overrides; never commit `.env`) |
| `Makefile` | `build` / `up` / `down` / `logs` / `migrate-docker` plus local (host-run) targets |

No secrets are baked into the image; everything secret comes from the environment at runtime.

## Local development (Docker)

```bash
cp .env.example .env        # defaults work for mock mode
make up                     # build image + start db (healthy) + api
make migrate-docker         # alembic upgrade head, run inside the api container
make seed                   # optional demo commerce data (host-run)
make logs                   # tail api + db
```

- API: `http://localhost:8010` · OpenAPI: `/docs` · Health: `GET /health` · Readiness: `GET /ready`
- The `api` service waits for `db` to become healthy (`depends_on: condition: service_healthy`).
- DB volume (`ecombot_pgdata`) persists across restarts; `make down` keeps it, `docker compose down -v` deletes it.
- Host-side alternative (no container for the API): `make db-up && make migrate && make run`.

## Configuration model

Precedence (highest first): **process env / `.env` > `config/*.yaml` > model defaults**.
Nested keys use `__` (e.g. `DATABASE__URL`, `LLM__OPENAI_API_KEY`); `CONFIG_DIR` overrides the
YAML directory. Only `src/ecommerce_support/core/config.py` reads the environment; settings are
validated by Pydantic at startup (misconfiguration fails loudly, e.g. production + default JWT
secret or `LLM__PROVIDER=mock` is refused — see `Settings._validate_environment`).

The compose file sets mock-mode defaults inline. To change any value for a deployment, override
the service `environment:` (or use an override file — see below); the container does **not**
read the host's `.env` automatically.

## Production-style deployment

`docker-compose.yml` is a local/dev stack (hardcoded dev credentials, mock providers, published
DB port). For a real deployment, override rather than edit:

```yaml
# docker-compose.prod.yml — example override (do not commit secrets)
services:
  db:
    restart: always
    # Do not publish the DB port in production; keep it on the compose network only.
    ports: !override []
    environment:
      POSTGRES_PASSWORD: ${DB_PASSWORD:?set DB_PASSWORD}
  api:
    environment:
      APP__ENV: production
      APP__LOG_FORMAT: structured
      DATABASE__URL: postgresql+asyncpg://ecombot:${DB_PASSWORD:?}@db:5432/ecombot
      AUTH__JWT_SECRET: ${JWT_SECRET:?generate: python -c "import secrets; print(secrets.token_urlsafe(64))"}
      LLM__PROVIDER: anthropic            # mock is rejected in production
      LLM__MODEL: claude-sonnet-4-5
      LLM__ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:?}
      LLM__EMBEDDING_PROVIDER: openai     # or ollama; dimension must stay 1536
      INTEGRATIONS__TICKETING_PROVIDER: jira
      INTEGRATIONS__JIRA_BASE_URL: ${JIRA_BASE_URL:?}
      INTEGRATIONS__JIRA_EMAIL: ${JIRA_EMAIL:?}
      INTEGRATIONS__JIRA_API_TOKEN: ${JIRA_API_TOKEN:?}
      INTEGRATIONS__JIRA_PROJECT_KEY: ${JIRA_PROJECT_KEY:?}
```

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm api alembic upgrade head
```

Production checklist:

- `APP__ENV=production` — startup **refuses** the default JWT secret, `APP__DEBUG=true`, and the mock LLM provider.
- Generate a strong `AUTH__JWT_SECRET` (`python -c "import secrets; print(secrets.token_urlsafe(64))"`).
- Set real LLM + embedding provider credentials; keep `LLM__EMBEDDING_DIMENSIONS=1536` (schema is `vector(1536)`; a mismatch fails `/ready` and the startup dimension check).
- Keep Postgres unpublished; terminate TLS at a reverse proxy/load balancer in front of the api service.
- Rotate provider secrets via your orchestrator's secret store; never bake them into images or commit `.env`.
- The image already runs as a non-root user and ships no dev tooling beyond the runtime venv.
- Scale the api service horizontally behind the proxy (stateless; all state in Postgres).
  Note: rate limiting is per-process in-memory (`core/ratelimit.py`), so limits are per instance.
- Run migrations as a release step (`migrate-docker` above), not on every container start.

## Migrations

Alembic is configured for the async engine and reads `DATABASE__URL` from validated settings:

```bash
make migrate          # from the host (venv; DATABASE__URL from .env)
make migrate-docker   # inside the api container (DATABASE__URL from compose)
make migrate-down     # roll back the last migration
```

Compose runs the api **without** migrations by design — apply them as a deploy step so a bad
migration cannot be retried blindly by restarting replicas.

## Health, readiness, observability

| Endpoint | Meaning |
| --- | --- |
| `GET /health` | Process is up (no dependencies) — used by the container healthcheck |
| `GET /ready` | DB reachable + embedding dimension check (FR-036) — use for LB readiness |
| `GET /metrics` | Prometheus text: chat turns, latency, escalations, feedback, tool calls + per-model LLM token/cost estimates |

Tracing (LangSmith/OTel) is opt-in: `OBSERVABILITY__TRACING_ENABLED=true` plus the relevant key;
it is off by default and no SDK is imported unless enabled.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `api` exits at startup with a JWT/debug/mock-provider error | `APP__ENV=production` validation — set a real `AUTH__JWT_SECRET`, `APP__DEBUG=false`, and a real `LLM__PROVIDER` |
| `api` healthy but `/ready` fails | DB not migrated (run `migrate-docker`), wrong `DATABASE__URL`, or embedding provider dimension mismatch |
| `readyz`/compose `api` restart loop on port 8010/8000 | Port already in use (e.g. an old stack): `docker ps` and `make down`, or change the host port mapping |
| `pg_isready` fails / db never healthy | Volume owned by another Postgres major, or port 5434 taken (`myexam-pg` uses 5433 on this host): inspect `docker compose logs db` |
| Chat answers refuse with "mock" behavior in prod | `LLM__PROVIDER=mock` is rejected in production; set a real provider + API key |
| Ticket escalation always fails | `INTEGRATIONS__TICKETING_PROVIDER` misconfigured — missing Jira/ServiceNow fields raise `ConfigurationError` at adapter construction; failures are reported truthfully (`TICKET_CREATION_FAILED`), never as fake success |
