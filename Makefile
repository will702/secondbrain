.PHONY: help dev db api workers web test eval lint client

help:
	@echo "dev      — start all services (database, API, workers, web) in one command"
	@echo "db       — start Postgres+pgvector (docker compose)"
	@echo "api      — run FastAPI dev server"
	@echo "workers  — run background job workers"
	@echo "web      — run Next.js dev server"
	@echo "test     — run API test suite"
	@echo "eval     — run AI evaluation suite (needs live LLM)"
	@echo "lint     — ruff check"
	@echo "client   — regenerate typed TS client from OpenAPI"

dev:
	@node scripts/start-all.mjs

db:
	docker compose up -d

api:
	cd apps/api && uv run uvicorn app.main:app --reload --port 8000

workers:
	cd apps/api && uv run python -m app.workers.runner

web:
	cd apps/web && pnpm dev

test:
	cd apps/api && uv run pytest -q

eval:
	cd apps/api && uv run python -m evals.run

lint:
	cd apps/api && uv run ruff check app tests

client:
	cd apps/api && uv run python -c "import app.main; import json; print(json.dumps(app.main.app.openapi()))" > /tmp/openapi.json
	cd apps/web && pnpm openapi
