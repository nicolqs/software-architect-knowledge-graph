.DEFAULT_GOAL := help
SHELL := /bin/bash

API_DIR := apps/api
WEB_DIR := apps/web

.PHONY: help install up down logs ps dev dev-api dev-web ingest test test-api test-web lint lint-api lint-web typecheck eval clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Targets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  %-12s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

install: ## Install all deps (root pnpm + api uv + web pnpm)
	pnpm install
	cd $(API_DIR) && uv sync
	cd $(WEB_DIR) && pnpm install

up: ## Start neo4j + postgres + langfuse (docker)
	docker compose up -d
	@echo "Waiting for services to be healthy..."
	@docker compose ps

down: ## Stop infra (keep volumes)
	docker compose down

logs: ## Tail infra logs
	docker compose logs -f --tail=100

ps: ## Show infra status
	docker compose ps

dev: ## Run api + web in parallel (foreground)
	@trap 'kill 0' EXIT; \
	$(MAKE) dev-api & \
	$(MAKE) dev-web & \
	wait

dev-api: ## Run FastAPI in reload mode
	cd $(API_DIR) && uv run uvicorn architect.main:app --host 0.0.0.0 --port 8000 --reload

dev-web: ## Run Vite dev server
	cd $(WEB_DIR) && pnpm dev

ingest: ## Ingest a repo into the graph. Usage: make ingest REPO=/path/to/repo
ifndef REPO
	$(error REPO is required. Usage: make ingest REPO=/path/to/repo)
endif
	cd $(API_DIR) && uv run python -m architect.ingest "$(REPO)"

test: test-api test-web ## Run all tests

test-api: ## Run api tests
	cd $(API_DIR) && uv run pytest

test-web: ## Run web tests
	cd $(WEB_DIR) && pnpm test

lint: lint-api lint-web ## Lint all

lint-api: ## Lint api (ruff + mypy)
	cd $(API_DIR) && uv run ruff check . && uv run mypy src

lint-web: ## Lint web (eslint + tsc)
	cd $(WEB_DIR) && pnpm lint && pnpm typecheck

typecheck: ## Typecheck both
	cd $(API_DIR) && uv run mypy src
	cd $(WEB_DIR) && pnpm typecheck

eval: ## Run agent eval harness (added in M2)
	cd $(API_DIR) && uv run python -m architect.evals.runner

clean: ## Remove caches and build artifacts (does NOT touch docker volumes)
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache -o -name node_modules -o -name dist -o -name .vite \) -prune -exec rm -rf {} +
