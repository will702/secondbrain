# Second Brain OS

An agentic personal operating system: drop information in, and the system understands it,
organizes it, detects tasks/deadlines/commitments, plans your calendar around them, and
answers questions about your life — with provenance for every AI-derived fact.

```
CAPTURE → UNDERSTAND → ORGANIZE → CONNECT → PRIORITIZE → PLAN → PREPARE → ACT → REFLECT → LEARN
```

## Stack

| Layer     | Technology                                                        |
|-----------|-------------------------------------------------------------------|
| Frontend  | Next.js 15 (App Router), TypeScript, Tailwind CSS                 |
| Backend   | Python 3.12, FastAPI, SQLAlchemy 2, Alembic                       |
| Database  | PostgreSQL 16 + pgvector                                          |
| AI        | Any OpenAI-compatible endpoint (default: local MLX / Ollama)      |
| Embeddings| fastembed `bge-small-en-v1.5` (384-dim, local, in-process)        |
| Jobs      | Postgres-backed durable queue (`FOR UPDATE SKIP LOCKED`)         |
| Files     | Local filesystem behind an S3-compatible storage adapter         |

## Repository layout

```
docs/        Product spec, architecture, data model, AI system, security, plan
apps/api/    FastAPI service + workers (ingestion, extraction, scheduling)
apps/web/    Next.js frontend (Home / Inbox / Calendar / Brain / Ask)
data/        Local file storage (gitignored)
```

## Quick start

1. **Database** — `docker compose up -d` (Postgres 16 + pgvector)
2. **API** — `cd apps/api && uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload`
3. **Workers** — `cd apps/api && uv run python -m app.workers.runner`
4. **Web** — `cd apps/web && pnpm install && pnpm dev`
5. **LLM** — point `LLM_BASE_URL` at any OpenAI-compatible server (default `http://localhost:8080/v1`)

See `docs/IMPLEMENTATION_PLAN.md` for the full roadmap and `docs/ARCHITECTURE.md` for the system design.

## Principles

- Documents and emails are **data, never instructions** (prompt-injection hardened and tested).
- Deterministic software for deterministic problems; LLMs only where semantic understanding pays.
- Every AI-created fact carries **provenance** (source document, page, confidence).
- Nothing consequential happens without an **approvable, auditable action proposal**.
