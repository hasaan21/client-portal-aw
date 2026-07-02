.PHONY: help setup install dev test fmt lint check seed migrate upgrade pdf-preview backup clean docker-build

PYTHON ?= python3
VENV   ?= .venv
BIN    := $(VENV)/bin

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## Create venv, install deps, install pre-commit hooks, copy .env
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e '.[dev]'
	$(BIN)/pre-commit install
	@test -f .env || cp .env.example .env
	@echo "\n\033[32mSetup complete.\033[0m Next: make migrate && make seed && make dev"

install: ## Reinstall the package (after adding deps)
	$(BIN)/pip install -e '.[dev]'

dev: ## Run the Flask dev server on http://localhost:5000
	$(BIN)/flask --app run.py --debug run --port 5000

test: ## Run the test suite
	$(BIN)/pytest

fmt: ## Format code (ruff format + black safety net)
	$(BIN)/ruff format .
	$(BIN)/ruff check --fix .

lint: ## Lint without modifying
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

check: lint test ## Lint + test (CI parity)

migrate: ## Create a new Alembic migration from model changes: `make migrate M="add foo"`
	$(BIN)/flask --app run.py db migrate -m "$(M)"

upgrade: ## Apply pending migrations
	$(BIN)/flask --app run.py db upgrade

seed: ## Seed 3 team users + demo clients
	$(BIN)/python scripts/seed.py

pdf-preview: ## Render sample PDFs to /tmp/aw-pdf-preview/ (synthetic client)
	$(BIN)/python scripts/pdf_preview.py $(if $(CLIENT),--client-id $(CLIENT))

backup: ## Timestamped SQLite backup into ./backups/
	$(BIN)/python scripts/backup_db.py

clean: ## Remove caches, venv, build artifacts
	rm -rf $(VENV) build dist *.egg-info .pytest_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +

docker-build: ## Build the production Docker image
	docker build -t aw-client-portal:local .
