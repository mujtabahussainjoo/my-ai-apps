# Multi-stage build using uv for reproducible, fast dependency installation.
# Runs as a non-root user; no secrets are baked into the image.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependency layer (cached unless pyproject/uv.lock change).
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project --no-dev

# Project source.
COPY README.md ./README.md
COPY src ./src
COPY config ./config
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY scripts ./scripts

RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

# uv is only needed to run commands; the venv is copied from the builder.
COPY --from=builder /usr/local/bin/uv /usr/local/bin/uv
COPY --from=builder /app /app

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Non-root user
RUN useradd --create-home --uid 10001 ecombot
USER ecombot

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)"

CMD ["uvicorn", "ecommerce_support.main:app", "--host", "0.0.0.0", "--port", "8000"]
