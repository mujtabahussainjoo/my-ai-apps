# One Dockerfile, several targets.
#
# api and worker share almost everything, so they share a stage. Compose selects
# the target with `target:`. Splitting these into separate files would mean each
# had to redeclare the base - and a `FROM base` in a separate file resolves to a
# Docker Hub image named "base", not to the stage you meant.
ARG PYTHON_VERSION=3.12

# ── base ─────────────────────────────────────────────────────────────────────
FROM python:${PYTHON_VERSION}-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# curl is for the healthcheck; libpq5 is psycopg's runtime library. Neither
# needs a compiler, so build-essential stays out of the image entirely.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN python -m venv $VIRTUAL_ENV \
    && pip install --upgrade pip \
    && pip install ".[live]"

COPY src ./src
COPY apps ./apps
COPY scripts ./scripts

# Non-root: a container that has to be talked out of writing to /app is one that
# cannot be talked into anything at all.
RUN useradd --create-home --uid 10001 financ && chown -R financ:financ /app
USER financ

COPY --chown=root:root --chmod=0755 infrastructure/docker/entrypoint.common.sh /usr/local/bin/entrypoint.common.sh

# ── api ──────────────────────────────────────────────────────────────────────
FROM base AS api
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=10s --start-period=30s --retries=5 \
    CMD curl -fsS http://localhost:8000/health/live || exit 1
COPY --chown=root:root --chmod=0755 infrastructure/docker/entrypoint.api.sh /usr/local/bin/entrypoint.api.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.api.sh"]
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ── worker ───────────────────────────────────────────────────────────────────
FROM base AS worker
COPY --chown=root:root --chmod=0755 infrastructure/docker/entrypoint.worker.sh /usr/local/bin/entrypoint.worker.sh
ENTRYPOINT ["/usr/local/bin/entrypoint.worker.sh"]
CMD ["python", "-m", "apps.worker.main"]
