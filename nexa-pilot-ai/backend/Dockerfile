FROM python:3.12-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY README.md ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    NEXAPILOT_HOST=0.0.0.0 \
    NEXAPILOT_PORT=8765 \
    NEXAPILOT_DATA_DIR=/data \
    NEXAPILOT_SECRET_BACKEND=file \
    NEXAPILOT_ENVIRONMENT=production

WORKDIR /app

COPY --from=builder /app /app
RUN useradd --create-home --uid 10001 nexapilot \
    && mkdir -p /data \
    && chown -R nexapilot:nexapilot /app /data

USER nexapilot

EXPOSE 8765

CMD ["uvicorn", "nexapilot.main:app", "--host", "0.0.0.0", "--port", "8765"]
