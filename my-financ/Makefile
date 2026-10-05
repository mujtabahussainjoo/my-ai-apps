SHELL := /bin/bash
PY := .venv/bin/python
PIP := .venv/bin/pip
COMPOSE := docker compose

.DEFAULT_GOAL := help
.PHONY: help setup check doctor up down logs ps migrate seed backtest paper api worker test lint fmt typecheck clean dashboard

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

doctor: ## Verify every built layer is wired up correctly (start here)
	$(PY) -m scripts.check_system

check: test lint doctor ## Tests, lint and a live self-check

setup: ## Create venv, install deps, write .env from template
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	@test -f .env || (cp .env.example .env && echo "created .env from template")
	@echo "→ edit .env, then run: make up"

up: ## Start postgres + redis
	$(COMPOSE) up -d postgres redis
	@echo "waiting for health..."
	@until [ "$$($(COMPOSE) exec -T postgres pg_isready -U financ 2>/dev/null | grep -c accepting)" = "1" ]; do sleep 1; done
	@echo "postgres ready"

down: ## Stop everything (keeps volumes)
	$(COMPOSE) down

nuke: ## Stop everything and DELETE all data volumes
	$(COMPOSE) down -v

logs: ## Tail service logs
	$(COMPOSE) logs -f --tail=100

ps: ## Show service status
	$(COMPOSE) ps

migrate: ## Create/upgrade DB tables from SQLAlchemy metadata
	$(PY) -m src.database.migrate

seed: ## Seed reference data (QUALIFY=strategy is an explicit operator override)
	$(PY) -m scripts.seed_database \
		$(if $(QUALIFY),--qualify $(QUALIFY),) \
		$(if $(REVOKE),--revoke $(REVOKE),) \
		$(if $(REASON),--reason "$(REASON)",)

backtest: ## Run a backtest (STRATEGY=breakout SOURCE=synthetic BARS=1500)
	$(PY) -m scripts.run_backtest --strategy $(or $(STRATEGY),breakout) \
		--source $(or $(SOURCE),synthetic) --bars $(or $(BARS),1500)

paper: ## Start the paper-trading loop (CYCLES=0 runs until interrupted)
	$(PY) -m scripts.start_paper_trading --cycles $(or $(CYCLES),0) \
		--interval $(or $(INTERVAL),$(POLL_INTERVAL))

download: ## Download historical candles for configured symbols
	$(PY) -m scripts.download_market_data

metrics: ## Recompute strategy metrics + qualification from stored runs
	$(PY) -m scripts.calculate_metrics

api: ## Run the API locally with reload
	$(PY) -m uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000

worker: ## Run the background worker (CYCLES=0 runs until interrupted)
	$(PY) -m apps.worker.main --cycles $(or $(CYCLES),0) \
		--interval $(or $(INTERVAL),60) \
		$(if $(SIGNALS_ONLY),--no-strategies,) \
		$(if $(STRATEGIES_ONLY),--no-signals,)

dashboard: ## Install + run the Next.js dashboard on :3000
	cd apps/dashboard && npm install && npm run dev

test: ## Run the test suite
	$(PY) -m pytest -q

cov: ## Run tests with coverage report
	$(PY) -m pytest --cov=src --cov-report=term-missing -q

lint: ## Lint (ruff check + format check)
	$(PY) -m ruff check src apps scripts tests
	$(PY) -m ruff format --check src apps scripts tests

fmt: ## Auto-format and fix imports
	$(PY) -m ruff check --fix src apps scripts tests
	$(PY) -m ruff format src apps scripts tests

typecheck: ## Static types
	$(PY) -m mypy src

clean: ## Remove caches and build artifacts
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov