.PHONY: install backend frontend desktop test lint format typecheck build bundle install-desktop uninstall-desktop frontend-build sidecar verify

install:
	cd backend && uv sync
	cd frontend && npm install
	cd desktop && npm install

backend:
	cd backend && uv run nexapilot

frontend:
	cd frontend && npm run dev

desktop:
	cd desktop && npm run dev

test:
	cd backend && uv run pytest
	cd frontend && npm test -- --run

lint:
	cd backend && uv run ruff check src tests && uv run ruff format --check src tests
	cd frontend && npm run lint --if-present

format:
	cd backend && uv run ruff check --fix src tests && uv run ruff format src tests

typecheck:
	cd backend && uv run mypy
	cd frontend && npm run typecheck

frontend-build:
	cd frontend && npm run build

# Requires Rust and the Tauri system libraries.
build: frontend-build sidecar
	cd desktop && npm run build

# Installer bundles for the current OS (.deb on Linux, .exe on Windows, .dmg on macOS).
bundle: build
	@echo "Packages: desktop/src-tauri/target/release/bundle/**"

install-desktop:
	bash install/linux/install.sh

uninstall-desktop:
	bash install/linux/uninstall.sh

sidecar:
	cd desktop && bash scripts/build-sidecar.sh

verify: lint typecheck test frontend-build
