# Architecture — Second Brain OS

Status: v1.0 · Companion docs: PRODUCT_SPEC.md, DATA_MODEL.md, AI_SYSTEM.md, SECURITY.md

## 1. System overview

A two-runtime monorepo plus a durable job backbone, deployed as cooperating processes
against one PostgreSQL instance. No microservices — module boundaries inside one API
process keep it deployable while preserving the option to split later.

```
┌─────────────┐   HTTPS    ┌───────────────────────────────────────────┐
│  apps/web   │──────────▶│              apps/api (FastAPI)            │
│  Next.js 15 │            │  routes → services → repositories → DB     │
└─────────────┘            │  policy layer (permissions/audit)          │
                           └───────┬───────────────────────┬───────────┘
                                   │ SQL (SQLAlchemy 2)    │ enqueue jobs
                                   ▼                       ▼
                           ┌──────────────┐      ┌─────────────────────┐
                           │ PostgreSQL16 │◀─────│ workers (same repo, │
                           │ + pgvector   │ SKIP │ own process)        │
                           └──────────────┘ LOCK │ ingestion pipeline, │
                                   ▲             │ triggers, planner   │
                           ┌────────┴────────┐    └──────────┬──────────┘
                           │ data/ files     │               │
                           └─────────────────┘               ▼
                                             ┌──────────────────────────┐
                                             │ LLM provider (OpenAI-    │
                                             │ compatible: local MLX /  │
                                             │ Ollama / OpenAI / …)     │
                                             │ + fastembed (local ONNX) │
                                             └──────────────────────────┘
```

### Components

| Component | Responsibility |
|---|---|
| `apps/api` routes | Auth, inbox upload, documents/entities/tasks/events/search/ask/calendar/proposals REST + OpenAPI |
| services/parsing | Type-specific extractors → structured `ParsedDocument` (sections, pages, text) |
| services/ingestion | Orchestrates parse → segment → chunk → embed → extract → graph write |
| services/extraction | Schema-validated LLM extraction (document profile, dates, tasks, commitments, entities, relations) |
| services/knowledge | Entity resolution (alias + embedding), graph mutations, merge |
| services/temporal | Date normalization, conflict/suspicion detection |
| services/retrieval | Hybrid search: tsvector BM25 + pgvector cosine + graph expansion + time/metadata filters |
| services/scheduling | Deterministic constraint planner + rescheduling (pure Python; OR-Tools-ready interface) |
| services/calendar | Local calendar, .ics import/export, Google adapter (dormant without credentials) |
| services/briefing | Attention engine, morning briefing, readiness, conflict surfacing |
| services/proposals | Proposal lifecycle: validate → policy → execute → audit |
| agents/ | LLM client, model router, prompts, tool registry, agent runners |
| workers/ | Job consumer loop, event triggers (FILE_ADDED, DEADLINE_APPROACHING, …) |

## 2. Ingestion architecture

Async, idempotent, staged — each stage is a checkpoint so retries never redo expensive work.

```
upload → store file (sha256 content address, data/files) → document row (status=received)
  → JOB ingest_document
     1. parse          (per mime; deterministic; stores ParsedDocument JSON)
     2. segment+chunk  (section-aware, 200–800 tokens, page/section spans kept)
     3. embed          (fastembed bge-small-en-v1.5 → pgvector 384-dim)
     4. extract        (LLM passes: profile → dates → tasks/commitments → entities/relations → summary)
     5. validate       (pydantic schemas; repair-retry ×2; failures → needs_review)
     6. normalize time (temporal engine; low confidence → review queue, never confirmed)
     7. resolve+write  (entity resolution; single DB transaction with provenance)
     8. trigger        (DEADLINE_APPROACHING, TASK_CREATED, CALENDAR_RECOMPUTE…)
```

Idempotency: document content-addressed by sha256; jobs carry `idempotency_key`; each stage
checks prior completion before running. A worker crash mid-pipeline resumes at the last
completed stage.

## 3. AI pipeline (see AI_SYSTEM.md for details)

Model routing table assigns purposes → models:
`extraction`, `reasoning`, `cheap_classify`, `embedding`, `summarize`. Default deployment
points all chat purposes at one local model; changing one line per purpose upgrades quality
selectively. Every LLM call is logged to `agent_runs` (tokens, latency, purpose) for cost and
regression observability. Results cached by `(purpose, model, prompt_hash)`.

## 4. Event architecture

Triggers persisted in the `jobs` table (durable queue) with `FOR UPDATE SKIP LOCKED`
claiming, exponential backoff, and poison-pill handling (max attempts → dead status +
alert). Event types (MVP): `FILE_ADDED`, `DOCUMENT_PROCESSED`, `DEADLINE_APPROACHING`,
`TASK_COMPLETED`, `TASK_MISSED`, `CALENDAR_CHANGED`, `PLAN_INVALIDATED`.

Example chain: `FILE_ADDED → parse/extract → Deadline discovered → knowledge graph write →
PLAN_INVALIDATED → planner recomputes soft blocks → briefing regenerated → proposal created`.

Handlers are idempotent (natural keys: document/task/entity ids; dedupe by `idempotency_key`).

## 5. Retrieval architecture

Hybrid, explainable, and filter-aware — never a single vector search.

1. **Lexical**: Postgres `tsvector` per chunk (english config), BM25-style ranking.
2. **Semantic**: pgvector cosine on 384-dim chunk embeddings (HNSW index).
3. **Metadata filters**: doc type, project, entity refs, date ranges.
4. **Time filters**: deadline/event windows ("things due next week").
5. **Graph traversal**: expand from matched entities to related documents/tasks/people.
6. **Fusion + explain**: reciprocal-rank fusion; each result carries which signals matched,
   so ASK answers can cite `why_matched`.

## 6. Integration architecture

`integrations` table stores provider credentials (encrypted at rest, see SECURITY.md) +
scopes + status. Each provider implements a narrow adapter interface:

```
CalendarProvider: list_events(range) | import_event | upsert_event | delete_event
MailProvider (P2): list_threads | get_thread | send (never called without explicit approval)
```

MVP ships: `LocalCalendarProvider` (DB-backed), `IcsProvider` (import/export),
`GoogleCalendarProvider` (full OAuth + sync code; **inactive until credentials configured** —
health endpoint reports `not_configured`, everything else keeps working).

Sync direction MVP: read Google → mirror into local `events`; write local → Google only via
approved proposals. Conflict rule: Google is source of truth for HARD events it owns.

## 7. Observability

- **Structured logging**: JSON lines (request_id, user_id, job_id, agent, purpose).
- **Agent runs**: every LLM invocation persisted (prompt hash, tokens in/out, latency, status) — the AI system's flight recorder.
- **Decision log**: planner/extraction decisions with reason + evidence refs.
- **Health endpoints**: `/healthz` (liveness), `/readyz` (DB, migrations, LLM reachable, embeddings model loaded — each reported independently so a dead LLM degrades, not kills).
- **Metrics-ready**: counters emitted as structured logs; Prometheus exporter is a Phase-2 addition, not an MVP dependency.

## 8. Deployment (MVP: single machine)

```
docker compose up -d            # postgres 16 + pgvector
uv run uvicorn app.main:app     # API
uv run python -m app.workers.runner   # workers (separate process, same codebase)
pnpm dev                        # Next.js (or `pnpm build && pnpm start`)
```

Production posture is container-ready: API and workers have Dockerfiles; the only stateful
dependency is Postgres + `data/` volume. Horizontal scale path: run N workers (queue is
SAFE with SKIP LOCKED), run API behind any reverse proxy. Postgres→Supabase is a connection-
string change (SQL avoids Postgres-only extensions beyond pgvector).

## 9. Key tradeoffs (summarized; full ADRs in IMPLEMENTATION_PLAN.md)

- **Postgres queue vs Redis/RQ/Celery**: chose Postgres — zero extra infra, transactional with
  domain writes, durable; tradeoff: polling latency (~1s) and no fancy routing. Acceptable at
  personal-OS scale; upgrade path documented.
- **Monolith-with-modules vs microservices**: chose modular monolith — a personal OS's load
  profile does not justify distribution; module boundaries + interface packages keep the
  split option cheap.
- **fastembed local vs cloud embeddings**: chose local for privacy/offline defaults; the
  provider interface accepts OpenAI/DashScope via env when quality matters more.
- **Pure-Python scheduler vs OR-Tools now**: chose pure Python first — explainable, testable,
  no heavy dependency; CP-SAT slots behind the same `Planner` interface when optimization
  complexity justifies it.
