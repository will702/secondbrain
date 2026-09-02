# Implementation Plan — Second Brain OS

Status: v1.0 · Milestones M0–M5 constitute the MVP build; Phases map to the roadmap below.

## Phase 0 — Foundation (M0)

**Deliverables**: runnable monorepo skeleton, database, CI-green baseline.
**Files/modules**: `docker-compose.yml`, `apps/api` (FastAPI app factory, config, logging,
health routes, Alembic env + baseline migration of the full schema), `apps/web` (Next.js 15 +
Tailwind shell, layout with 5-surface nav), OpenAPI→TS client generation script,
`.env.example`, Makefile.
**Migrations**: `0001_initial` — all tables in DATA_MODEL.md.
**APIs**: `GET /healthz`, `GET /readyz` (DB/migrations/LLM/embeddings each reported).
**UI**: app shell with Home/Inbox/Calendar/Brain/Ask placeholders.
**Tests**: config load, health endpoints, one DB roundtrip.
**Acceptance**: `docker compose up -d` + API + web run; `/readyz` green (LLM: degraded-OK).

## Phase 1 — Ingestion (M1)

**Deliverables**: auth + universal inbox with parsing/chunking/embedding.
**Files**: `core/security.py`, `routes/auth.py|inbox.py|documents.py`, `services/parsing/*`
(pdf, docx, pptx, xlsx, csv, md, txt), `services/ingestion/` (segmenter, chunker),
`agents/embeddings.py` (fastembed), `workers/` (queue + ingest_document handler),
`services/storage.py` (local fs adapter).
**Migrations**: none beyond Phase 0 (documents/chunks already exist).
**APIs**: `POST /auth/register|login|logout`, `POST /inbox/upload` (multipart, bulk),
`GET /documents`, `GET /documents/{id}` (chunks, status), `GET /documents/{id}/file`.
**UI**: Inbox drop zone with per-file status; document list; document detail (parsed text).
**Tests**: parsing fixtures (pdf/docx/pptx/xlsx/md), chunker invariants (size bounds,
section/page spans), auth flows, idempotent re-upload, queue claim/backoff.
**Acceptance**: upload sample syllabus PDF → status transitions to `processed`, chunks with
384-dim vectors in DB; duplicate upload is a no-op.

## Phase 2 — Intelligence (M2)

**Deliverables**: schema-validated LLM extraction, temporal engine, knowledge graph,
conflict detection, review queue.
**Files**: `agents/llm_client.py`, `agents/router.py`, `agents/prompts/*`,
`services/extraction/*` (profile, dates, tasks, commitments, entities, relations),
`services/temporal/` (normalizer, conflict detector), `services/knowledge/` (resolution,
graph writes), `routes/review.py|entities.py`, review resolution flow.
**Migrations**: review_items already in baseline; none new.
**APIs**: `GET /entities` (graph JSON), `GET /entities/{id}`, `GET /review`, `POST /review/{id}/resolve`,
`GET /deadlines`, `GET /tasks`, `GET /decisions`.
**UI**: BRAIN graph browser (entity list → detail with provenance + related docs); Inbox
review cards (confirm/edit/reject extracted deadlines/tasks).
**Tests**: quote-verification guard, validation-repair loop, temporal normalizer table
(explicit/vague/relative cases), conflict detection (two dates → review item), entity
resolution (alias + case variants merge), injection defense suite, extraction golden
fixtures with mocked LLM.
**Acceptance**: fixture corpus yields "Assignment 4 due Oct 13 → belongs_to Machine Learning"
with page provenance; ambiguous "sometime next week" produces review item, never an event.

## Phase 3 — Calendar & Planning (M4)

**Deliverables**: local calendar, .ics import/export, Google adapter (creds-optional),
deterministic scheduler, rescheduling, decision log.
**Files**: `services/calendar/` (local, ics, google adapter + oauth routes),
`services/scheduling/` (planner core, availability, rescheduler), `routes/calendar.py|schedule.py`,
`POST /auth/google/*` OAuth flow.
**Migrations**: none new (events/proposals in baseline).
**APIs**: `GET/POST /events`, `POST /calendar/import-ics`, `GET /calendar/export.ics`,
`GET /calendar/google/status|/connect|/callback`, `POST /schedule/recompute`,
`GET /schedule` (week view data incl. soft blocks + reasons), `POST /events/{id}/missed`
(reschedule trigger).
**UI**: Calendar week view (HARD/SOFT/DEADLINE/FOCUS legend), "Recompute plan" action,
integration settings card (Google: connect / not-configured notice).
**Tests**: availability computation, planner constraints (no overlap, min session, deps,
work hours, buffers), exam-prep staging scenario, missed-session recompute (hard events
untouched), ics round-trip, google adapter with stubbed OAuth (creds-absent → inactive).
**Acceptance**: exam Friday → Mon–Thu focus blocks proposed respecting real availability;
deleting a session recomputes plan; every placement has an `ai_decisions` row.

## Phase 4 — Command Center (M3)

**Deliverables**: hybrid retrieval + ASK with citations.
**Files**: `services/retrieval/` (lexical, vector, graph, fusion, explain), `agents/ask_agent.py`
(tool-calling over retrieval + structured queries), `routes/search.py|ask.py`.
**Migrations**: none.
**APIs**: `GET /search?q=` (explainable results), `POST /ask` (answer + citations + path used).
**UI**: ASK surface with streaming-free simple Q→A, citation chips linking to document pages.
**Tests**: hybrid fusion ranking, time-filter queries ("due next week"), citation
verification, relational vs semantic routing.
**Acceptance**: "what's due next week" and "everything about the ML midterm" return correct,
cited answers from structured deadlines + retrieval respectively.

## Phase 5 — Proactive Intelligence (M5)

**Deliverables**: briefing/attention/readiness/conflicts, action proposals with
approve/modify/reject + batch, audit trail, "Why?" explanations.
**Files**: `services/briefing/` (attention engine, readiness, morning briefing),
`services/proposals/` (lifecycle + executors per action_type), `routes/proposals.py|briefing.py`,
`services/policy.py`.
**Migrations**: none.
**APIs**: `GET /briefing`, `GET /proposals`, `POST /proposals/{id}/approve|reject|modify`,
`POST /proposals/approve-batch`, `GET /audit`.
**UI**: HOME briefing (today, priorities, risks ⚠, suggestions with Why? popover, upcoming
3/7/30); proposal drawer with diff + Approve/Modify/Reject; batch approve.
**Tests**: attention scoring, readiness components, proposal lifecycle incl. modify +
execution + audit rows, permission gating matrix (levels × actions), recovery plan for
overdue tasks.
**Acceptance**: full loop — drop docs → extracted deadlines → proposed focus blocks →
approve → events on calendar → HOME reflects change; every AI suggestion explains itself.

## Phase 6 — Integrations & beyond (post-MVP)

Gmail sync + drafts (Mail agent), study intelligence UI (mastery, flashcards, spaced
repetition), meeting briefs, deeper memory/procedural learning, graph visualization,
OR-Tools CP-SAT planner upgrade, mobile (Expo), hosted multi-tenant deployment, Prometheus
metrics, Obsidian vault importer (`~/second-brain/brain` markdown → inbox).

---

## ADR log (decisions & tradeoffs)

- **ADR-001 Modular monolith over microservices.** Personal-OS load (1 user) doesn't justify
  distribution; module boundaries + adapter interfaces keep the split cheap later. Rejected:
  microservices (operational cost), single Next.js app (Python parsing/scheduling ecosystem).
- **ADR-002 Postgres-backed job queue (SKIP LOCKED) over Celery/Redis/River.** Transactional
  with domain writes, zero infra, durable, idempotent by design. Tradeoff: ~1s poll latency,
  no delayed-queue features — fine at this scale; migration path: swap `Queue` interface
  implementation, handlers unchanged.
- **ADR-003 fastembed local embeddings over cloud APIs.** Privacy-first default (nothing
  leaves the machine), offline-capable, 384-dim keeps pgvector fast. Tradeoff: quality below
  text-embedding-3-large; mitigated by hybrid retrieval carrying lexical+graph signals;
  provider interface allows env-swap.
- **ADR-004 Provenance as embedded JSONB, not a `sources` table.** 1:1 ownership, always read
  with parent, no independent queries. Rejected normalized table: join cost, no benefit.
- **ADR-005 Pure-Python deterministic scheduler now; OR-Tools CP-SAT behind the same
  interface later.** Explainability + testability first; heavy dependency only when
  optimization complexity earns it. LLM estimates inputs, never places blocks.
- **ADR-006 Tool-call-as-schema structured output.** Most reliable JSON forcing on
  OpenAI-compatible local servers without `response_format`; pydantic validation + bounded
  repair; quote-verification kills most extraction hallucinations cheaply.
- **ADR-007 Creds-optional Google Calendar.** OAuth code ships fully; system never blocks on
  external credentials (local calendar + .ics fallback). Sync degrades gracefully.
- **ADR-008 Deterministic orchestrator (classifier + dispatch), not an LLM meta-agent.**
  Routing is classification; a lookup table is testable and injection-resistant.
- **ADR-009 Operational objects (tasks/deadlines/events) are not entity rows.** They need
  relational queries, not embedding resolution; FKs into the graph + unified graph view give
  the same query power without row duplication. (DATA_MODEL.md §1)
- **ADR-010 Fresh build over extending `~/setup-second-brain`.** Vault-file architecture and
  Postgres/web spec are divergent; a hybrid would compromise both. Old kit remains prior art;
  vault import planned Phase 6.
