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
| AI        | local-ai stack (~/ai): Qwen3.5-4B `fast` / Qwen3.5-9B `smart` |
| Embeddings| Qwen3-Embedding-0.6B (1024-dim) + Qwen3-Reranker-0.6B via local-ai |
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
3. **Workers** — `make workers` (background ingestion/extraction/planning)
4. **Web** — `cd apps/web && pnpm install && pnpm dev` → http://localhost:3000
5. **AI** — the [local-ai stack](../ai/README.md) at `~/ai` provides the LLM
   (`fast`/`smart` aliases), 1024-d embeddings, and reranking behind one
   OpenAI-compatible endpoint on `127.0.0.1:8080`:
   ```sh
   local-ai status        # auto-starts on first use; no LaunchAgents
   local-ai doctor        # verifies models, embeddings, reranker end-to-end
   ```
   Any OpenAI-compatible endpoint still works — point `LLM_BASE_URL` at it.
   Extraction sends `chat_template_kwargs: {enable_thinking: false}` and tight
   `max_tokens` caps; without those, thinking-mode models stall the sequential
   local server for minutes per call. Retrieval embeddings/reranking use the
   same server (`EMBEDDING_PROVIDER=localai`, 1024-d); `fastembed` (384-d)
   remains available as a fallback provider.
6. **Sample data** — `cd apps/api && uv run python scripts/seed.py` (demo user +
   syllabus/assignment/schedule corpus), then sign in at the web app or browse
   http://localhost:8000/docs for the full API.

See `docs/IMPLEMENTATION_PLAN.md` for the full roadmap and `docs/ARCHITECTURE.md` for the system design.

## Principles

- Documents and emails are **data, never instructions** (prompt-injection hardened and tested).
- Deterministic software for deterministic problems; LLMs only where semantic understanding pays.
- Every AI-created fact carries **provenance** (source document, page, confidence).
- Nothing consequential happens without an **approvable, auditable action proposal**.

## Implementation status (MVP complete)

All six milestones built and verified: 87 backend tests, 14/14 eval cases (incl. live 9B-model
extraction), full loop demoed live — upload → extraction (deadlines/tasks/commitments/entities
with provenance) → knowledge graph → hybrid search + ASK with citations → deterministic
planner → proposals → approval → focus events on the calendar → daily briefing.

What works today: auth, universal inbox (8 formats + zip), parsing/chunking/local embeddings,
LLM extraction with quote-verification and injection quarantine, deterministic temporal
normalization + conflict detection, review queue, knowledge graph, hybrid retrieval,
command bar, local calendar + .ics + creds-optional Google adapter, constraint scheduler with
rescheduling, attention engine + briefing + readiness, permission levels 0–4, action
proposals with audit log. Phase 2+ (Gmail, study UI, autonomy workflows) per
`docs/IMPLEMENTATION_PLAN.md`.

```sh
make test   # 87 tests      make eval   # eval suite (needs live LLM)
```
