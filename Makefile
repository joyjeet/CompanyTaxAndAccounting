.PHONY: help install run dev test test-isolation lint typecheck migrate migrate-create migrate-down up down logs psql shell fmt seed-demo frontend-install frontend-dev frontend-build frontend-test pr

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

pr: ## Open a PR for your work and auto-merge when green: make pr m="what changed"
	@./scripts/open_pr.sh "$(m)"

install: ## Install deps with pip into .venv (use `uv pip install -e .[dev]` if you prefer uv)
	python3.12 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -e ".[dev]"

up: ## Start db + redis + app via docker-compose
	docker compose up -d --build

down: ## Stop and remove containers
	docker compose down -v

logs: ## Tail app logs
	docker compose logs -f app

run: ## Run API locally (expects DB up)
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev: up logs ## Start stack and tail logs

migrate: ## Apply all migrations (runs as owner)
	docker compose run --rm app alembic upgrade head

migrate-create: ## Create a new alembic revision: make migrate-create m="message"
	docker compose run --rm app alembic revision -m "$(m)"

migrate-down: ## Rollback one migration
	docker compose run --rm app alembic downgrade -1

test: ## Run all tests inside the app container against the test DB
	docker compose run --rm app pytest

test-isolation: ## Run only the cross-tenant isolation tests
	docker compose run --rm app pytest tests/isolation -v

lint: ## Ruff lint
	ruff check .

fmt: ## Ruff format
	ruff format .

typecheck: ## Mypy
	mypy app

psql: ## Open a psql shell as the owner role
	docker compose exec db psql -U ctaa_owner -d ctaa

shell: ## Open a bash shell in the app container
	docker compose run --rm app bash

seed-demo: ## Seed one demo firm + one client + COA + period and print IDs
	docker compose run --rm app python -m scripts.seed_demo

# ----- Frontend ---------------------------------------------------------- #
frontend-install: ## Install frontend npm deps
	cd frontend && npm install

frontend-dev: ## Run Vite dev server on :5173 (expects backend at :8000)
	cd frontend && npm run dev

frontend-build: ## Build the frontend for production (dist/)
	cd frontend && npm run build

frontend-test: ## Run frontend vitest suite
	cd frontend && npm run test
