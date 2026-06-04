.PHONY: help install dev lint fmt test check run up up-tls down logs key reindex

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Install runtime dependencies
	pip install -r requirements.txt

dev:  ## Install with dev tooling (ruff, pytest) + console scripts
	pip install -e ".[dev]"

lint:  ## Run ruff lint
	ruff check .

fmt:  ## Auto-format with ruff
	ruff format .

test:  ## Run the test suite (offline)
	pytest

check: lint test  ## Lint + format-check + test (what CI runs)
	ruff format --check .

run:  ## Run the API locally (embedded Qdrant); set BRAIN_API_KEYS first
	uvicorn api.server:app --reload

up:  ## Start the stack (Qdrant private, API on loopback)
	docker compose up -d --build

up-tls:  ## Start with HTTPS (set BRAIN_DOMAIN + ACME_EMAIL in .env)
	docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d --build

down:  ## Stop the stack
	docker compose down

logs:  ## Tail API logs
	docker compose logs -f brain-api

key:  ## Generate a new API key (usage: make key AGENT=cursor)
	python scripts/gen_key.py $(or $(AGENT),default)

reindex:  ## Rebuild the vector index from the vault
	@curl -s -X POST http://127.0.0.1:8000/reindex \
		-H "Authorization: Bearer $${BRAIN_API_KEY:?set BRAIN_API_KEY}" ; echo
