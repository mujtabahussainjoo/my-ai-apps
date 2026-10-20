export PATH := $(HOME)/.local/bin:$(PATH)
# Prefer Docker Compose v2 (`docker compose`); fall back to legacy v1 for older hosts.
COMPOSE ?= $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo "docker-compose")
.DEFAULT_GOAL := help

.PHONY: help install sync lint format format-check typecheck test test-cov check run db-up db-down db-logs migrate migrate-down migrate-docker seed ingest evaluate evaluate-agents evaluate-all build up down logs

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies (creates .venv, syncs lockfile)
	uv sync

sync: ## Re-sync dependencies from lockfile
	uv sync --frozen

lint: ## Ruff lint
	uv run ruff check .

format: ## Ruff auto-format
	uv run ruff format .

format-check: ## Check formatting without writing
	uv run ruff format --check .

typecheck: ## Mypy strict type check
	uv run mypy src

test: ## Run unit + integration + security + e2e tests (mocks; db tests skip if no Postgres)
	uv run pytest

test-cov: ## Run tests with coverage report
	uv run pytest --cov --cov-report=term-missing

check: lint format-check typecheck test ## Run all quality gates

run: ## Run the API service locally (requires DATABASE_URL or starts degraded)
	uv run uvicorn ecommerce_support.main:app --host $${SERVICE_HOST:-0.0.0.0} --port $${SERVICE_PORT:-8000} --reload

db-up: ## Start PostgreSQL (pgvector) via docker compose
	$(COMPOSE) up -d db

db-down: ## Stop compose services (keeps volume)
	$(COMPOSE) stop

db-logs: ## Tail database logs
	$(COMPOSE) logs -f db

build: ## Build the API Docker image
	$(COMPOSE) build

up: ## Start the full stack (db + api) via docker compose
	$(COMPOSE) up -d --build

down: ## Stop the full stack (keeps the db volume)
	$(COMPOSE) down

logs: ## Tail api + db logs
	$(COMPOSE) logs -f api db

migrate-docker: ## Apply migrations inside the api container (uses the compose DATABASE__URL)
	$(COMPOSE) run --rm api alembic upgrade head

migrate: ## Apply database migrations
	uv run alembic upgrade head

migrate-down: ## Roll back last migration
	uv run alembic downgrade -1

seed: ## Seed demo commerce + policy data
	uv run python scripts/seed_demo_data.py

ingest: ## Ingest policy documents into pgvector
	uv run python scripts/ingest_documents.py

evaluate: ## Run RAG evaluation baseline
	uv run python scripts/evaluate_rag.py

evaluate-agents: ## Run routing/tool-selection evaluation baseline (no DB required)
	uv run python scripts/evaluate_agents.py

evaluate-all: evaluate evaluate-agents ## Run both evaluation baselines
