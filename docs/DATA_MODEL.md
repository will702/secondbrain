# Data Model — Second Brain OS

Status: v1.0 · Implemented as SQLAlchemy 2 models + Alembic migrations. SQL below is the
reference DDL (PostgreSQL 16 + pgvector).

## 1. Design policies (the "entity vs specialized table vs both" question)

1. **Conceptual nodes are `entities`** — Person, Course, Project, Organization, Topic,
   Concept, Location, Goal. These are the nodes of the knowledge graph: they get resolved
   (alias + embedding matching), mentioned in chunks, and connected by typed predicates.
2. **Operational objects are specialized tables** — Task, Deadline, Event, Document,
   Commitment, Email, Note. They are queried relationally (by status, date, project) and
   never need embedding-based resolution, so duplicating them as entity rows buys nothing.
   They link into the graph via FKs (`project_id`, `person_entity_id`, `related_entity_id`).
3. **Hybrid nodes get both** — Project and Person carry rich operational fields, so each has
   a specialized table 1:1-joined to its entity row (`projects.entity_id`, `people.entity_id`).
4. **The graph browser view unifies both layers**: conceptual entities from
   `entity_relationships` + operational links from FKs (`task.project_id`, `document.project_id`).
5. **Provenance is an embedded JSONB object** (shared `Provenance` shape: source document,
   chunk, page, quote, extractor, timestamps) rather than a normalized `sources` table.
   Rationale (ADR-004): every provenance record is owned 1:1 by exactly one parent row, is
   always read with that parent, and no query pattern needs sources independently. A
   `sources` table would add a join to every read with zero query benefit.
6. **Temporal rows preserve truth**: raw expression, normalized instant, timezone,
   confidence, explicit-vs-inferred, and source are never collapsed into one date column.

## 2. Enums

```sql
document_kind:  syllabus | lecture_slides | assignment | exam | meeting_notes | schedule |
                email_export | certificate | competition | notes | reference | other
document_status: received | parsing | embedding | extracting | review | processed | failed
entity_kind:    person | course | project | organization | topic | concept | location | goal
event_kind:     hard | soft | deadline | focus | reminder
task_status:    proposed | pending | scheduled | in_progress | done | missed | cancelled
confidence:     confirmed | likely | possible            -- commitments
deadline_status: tentative | confirmed | rejected
memory_layer:   working | episodic | semantic | procedural
proposal_status: pending | approved | modified | rejected | executed | failed
risk_level:     low | medium | high
job_status:     pending | claimed | done | failed | dead
review_status:  open | resolved | dismissed
```

## 3. Schema (reference DDL)

### Identity & access

```sql
CREATE TABLE users (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email          CITEXT UNIQUE NOT NULL,
  password_hash  TEXT NOT NULL,
  display_name   TEXT NOT NULL,
  timezone       TEXT NOT NULL DEFAULT 'Asia/Jakarta',
  autonomy_level SMALLINT NOT NULL DEFAULT 1,   -- permission Level 0..4, see SECURITY.md
  work_hours     JSONB   NOT NULL DEFAULT '{"start":"09:00","end":"22:00"}',
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash  TEXT UNIQUE NOT NULL,
  expires_at  TIMESTAMPTZ NOT NULL,
  user_agent  TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Per-action grants beyond the global autonomy level (allow/denylist).
CREATE TABLE permissions (
  id         BIGSERIAL PRIMARY KEY,
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  action     TEXT NOT NULL,          -- e.g. 'calendar.write_google', 'email.draft'
  granted    BOOLEAN NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, action)
);
```

### Documents & chunks

```sql
CREATE TABLE documents (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  sha256            TEXT NOT NULL,
  original_filename TEXT NOT NULL,
  storage_path      TEXT NOT NULL,
  mime_type         TEXT NOT NULL,
  doc_kind          document_kind NOT NULL DEFAULT 'other',
  title             TEXT,
  topic             TEXT,
  summary           TEXT,
  importance        REAL CHECK (importance BETWEEN 0 AND 1),
  project_id        UUID REFERENCES projects(id),
  page_count        INT,
  status            document_status NOT NULL DEFAULT 'received',
  error             TEXT,
  provenance        JSONB,                       -- extraction trace
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  processed_at      TIMESTAMPTZ,
  UNIQUE (user_id, sha256)                       -- idempotent re-upload
);

CREATE TABLE document_chunks (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index INT NOT NULL,
  section     TEXT,
  page        INT,
  text        TEXT NOT NULL,
  token_count INT NOT NULL,
  embedding   vector(384),                       -- fastembed bge-small-en-v1.5
  tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (document_id, chunk_index)
);
CREATE INDEX chunks_embedding_idx ON document_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX chunks_tsv_idx       ON document_chunks USING gin (tsv);
```

### Knowledge graph

```sql
CREATE TABLE entities (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind             entity_kind NOT NULL,
  name             TEXT NOT NULL,
  normalized_name  TEXT NOT NULL,                -- lowercased, de-punctuated
  description      TEXT,
  aliases          JSONB NOT NULL DEFAULT '[]',
  embedding        vector(384),                   -- used for resolution matching
  confidence       REAL NOT NULL DEFAULT 0.5,
  merged_into_id   UUID REFERENCES entities(id),  -- resolution history, read-only after merge
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, kind, normalized_name)         -- natural key for idempotent upserts
);
CREATE INDEX entities_user_kind_idx ON entities (user_id, kind);

CREATE TABLE entity_relationships (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  subject_entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  predicate         TEXT NOT NULL,                -- teaches | belongs_to | participant | related_to | required_for | …
  object_entity_id  UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  confidence        REAL NOT NULL DEFAULT 0.5,
  provenance        JSONB NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (subject_entity_id, predicate, object_entity_id)
);

CREATE TABLE entity_mentions (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  chunk_id      UUID NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
  entity_id     UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  surface_form  TEXT NOT NULL,
  span_start    INT, span_end INT,
  confidence    REAL NOT NULL DEFAULT 0.5,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX mentions_chunk_idx ON entity_mentions (chunk_id);
CREATE INDEX mentions_entity_idx ON entity_mentions (entity_id);
```

### Projects, people (hybrid nodes)

```sql
CREATE TABLE projects (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  entity_id  UUID NOT NULL REFERENCES entities(id) UNIQUE,
  name       TEXT NOT NULL,
  kind       TEXT NOT NULL DEFAULT 'project',     -- course | competition | work | personal
  status     TEXT NOT NULL DEFAULT 'active',
  color      TEXT,
  starts_on  DATE, ends_on DATE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE people (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  entity_id    UUID NOT NULL REFERENCES entities(id) UNIQUE,
  name         TEXT NOT NULL,
  email        TEXT,
  organization TEXT,
  role         TEXT,                             -- professor | teammate | advisor | …
  relationship TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Work, time, commitments

```sql
CREATE TABLE tasks (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                 UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title                   TEXT NOT NULL,
  description             TEXT,
  project_id              UUID REFERENCES projects(id),
  related_entity_id       UUID REFERENCES entities(id),
  status                  task_status NOT NULL DEFAULT 'pending',
  priority                SMALLINT NOT NULL DEFAULT 3,      -- 1 (highest) .. 5
  importance              REAL DEFAULT 0.5,
  estimated_minutes       INT,
  minimum_session_minutes INT DEFAULT 30,
  difficulty              SMALLINT DEFAULT 3,               -- 1..5
  splittable              BOOLEAN NOT NULL DEFAULT true,
  preferred_time_of_day   TEXT DEFAULT 'any',               -- morning|afternoon|evening|any
  energy                  TEXT DEFAULT 'medium',            -- low|medium|high
  deadline_id             UUID REFERENCES deadlines(id),
  provenance              JSONB,
  confidence              REAL NOT NULL DEFAULT 0.5,
  completed_at            TIMESTAMPTZ,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX tasks_user_status_idx ON tasks (user_id, status);
CREATE INDEX tasks_project_idx     ON tasks (project_id);

CREATE TABLE task_dependencies (
  id                 BIGSERIAL PRIMARY KEY,
  task_id            UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  depends_on_task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
  UNIQUE (task_id, depends_on_task_id),
  CHECK (task_id <> depends_on_task_id)
);

CREATE TABLE deadlines (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title          TEXT NOT NULL,
  normalized_at  TIMESTAMPTZ,                     -- NULL until confidently resolved
  date_is_exact  BOOLEAN NOT NULL DEFAULT false,  -- has unambiguous day+time
  raw_expression TEXT NOT NULL,                   -- original text, never discarded
  timezone       TEXT NOT NULL,
  confidence     REAL NOT NULL DEFAULT 0.3,       -- low default; high bar to confirm
  explicit       BOOLEAN NOT NULL DEFAULT false,  -- stated vs AI-inferred
  status         deadline_status NOT NULL DEFAULT 'tentative',
  project_id     UUID REFERENCES projects(id),
  task_id        UUID REFERENCES tasks(id),
  provenance     JSONB NOT NULL,                  -- document/page/quote
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX deadlines_user_when_idx ON deadlines (user_id, normalized_at);

CREATE TABLE commitments (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  text            TEXT NOT NULL,                  -- "I'll send it tomorrow"
  direction       TEXT NOT NULL,                  -- user_promised | other_promised
  confidence      confidence NOT NULL DEFAULT 'possible',
  person_entity_id UUID REFERENCES entities(id),
  project_id      UUID REFERENCES projects(id),
  deadline_id     UUID REFERENCES deadlines(id),
  status          TEXT NOT NULL DEFAULT 'open',   -- open | fulfilled | dismissed
  provenance      JSONB NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE events (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind              event_kind NOT NULL,
  title             TEXT NOT NULL,
  starts_at         TIMESTAMPTZ NOT NULL,
  ends_at           TIMESTAMPTZ NOT NULL,
  all_day           BOOLEAN NOT NULL DEFAULT false,
  timezone          TEXT NOT NULL,
  location          TEXT,
  description       TEXT,
  provider          TEXT NOT NULL DEFAULT 'local',  -- local | google | ics
  provider_event_id TEXT,
  task_id           UUID REFERENCES tasks(id),
  project_id        UUID REFERENCES projects(id),
  editable          BOOLEAN NOT NULL DEFAULT true,
  source_proposal_id UUID REFERENCES action_proposals(id),
  provenance        JSONB,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX events_user_range_idx ON events (user_id, starts_at);
CREATE INDEX events_provider_idx   ON events (user_id, provider, provider_event_id);
```

### Notes, email (schema now, sync Phase 2), study

```sql
CREATE TABLE notes (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title      TEXT NOT NULL,
  content    TEXT NOT NULL,
  kind       TEXT NOT NULL DEFAULT 'note',        -- note | briefing | study_material | draft
  project_id UUID REFERENCES projects(id),
  provenance JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE emails (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider            TEXT NOT NULL DEFAULT 'gmail',
  provider_message_id TEXT NOT NULL,
  thread_id           TEXT,
  from_email          TEXT,
  from_name           TEXT,
  recipients          JSONB NOT NULL DEFAULT '[]',
  subject             TEXT,
  body_text           TEXT,
  snippet             TEXT,
  received_at         TIMESTAMPTZ,
  importance          REAL,
  project_id          UUID REFERENCES projects(id),
  raw                 JSONB,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, provider, provider_message_id)
);

CREATE TABLE study_concepts (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  project_id       UUID REFERENCES projects(id),
  entity_id        UUID REFERENCES entities(id),
  name             TEXT NOT NULL,
  description      TEXT,
  mastery          REAL NOT NULL DEFAULT 0,       -- 0..1, Bayesian-ish update, see AI_SYSTEM.md
  last_reviewed_at TIMESTAMPTZ,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE study_sessions (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  concept_id   UUID NOT NULL REFERENCES study_concepts(id) ON DELETE CASCADE,
  scheduled_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  score        REAL,                              -- quiz/self-assessment result 0..1
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Memory, observability, actions

```sql
CREATE TABLE memories (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  layer          memory_layer NOT NULL,
  key            TEXT,                            -- semantic/procedural: stable identifier
  content        TEXT NOT NULL,
  importance     REAL NOT NULL DEFAULT 0.5,
  confidence     REAL NOT NULL DEFAULT 0.5,
  embedding      vector(384),
  access_count   INT NOT NULL DEFAULT 0,
  last_accessed_at TIMESTAMPTZ,
  expires_at     TIMESTAMPTZ,                     -- decayed memories are pruned, not deleted, until GC
  provenance     JSONB,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX memories_user_layer_idx ON memories (user_id, layer);

CREATE TABLE agent_runs (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID,
  agent        TEXT NOT NULL,                     -- inbox | temporal | planning | ask | …
  purpose      TEXT NOT NULL,                     -- extraction | reasoning | classify | summarize
  model        TEXT NOT NULL,
  prompt_hash  TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT 'running',   -- running | succeeded | failed
  input_tokens INT, output_tokens INT,
  latency_ms   INT,
  error        TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX agent_runs_user_idx ON agent_runs (user_id, created_at);

CREATE TABLE ai_decisions (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  agent      TEXT NOT NULL,
  decision   TEXT NOT NULL,                       -- "Move assignment prep to Wednesday"
  reason     TEXT NOT NULL,                       -- "Thursday blocked by meeting"
  evidence   JSONB NOT NULL,                      -- refs: {events:[id], deadlines:[id], tasks:[id]}
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE action_proposals (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  action_type    TEXT NOT NULL,                   -- create_event | update_event | delete_event |
                                                   -- create_task | update_task | create_note | send_email
  payload        JSONB NOT NULL,                  -- typed payload per action_type (pydantic-validated)
  reason         TEXT NOT NULL,                   -- human-readable justification
  evidence       JSONB,                           -- decision-log refs
  risk_level     risk_level NOT NULL DEFAULT 'low',
  proposed_by    TEXT NOT NULL,                   -- agent name | user
  status         proposal_status NOT NULL DEFAULT 'pending',
  expires_at     TIMESTAMPTZ,
  decided_at     TIMESTAMPTZ,
  executed_at    TIMESTAMPTZ,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX proposals_user_status_idx ON action_proposals (user_id, status);

CREATE TABLE action_executions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  proposal_id UUID NOT NULL REFERENCES action_proposals(id) ON DELETE CASCADE,
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status      TEXT NOT NULL,                      -- success | failed
  result      JSONB,
  error       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE audit_logs (
  id          BIGSERIAL PRIMARY KEY,
  user_id     UUID,
  actor       TEXT NOT NULL,                      -- user | agent:<name> | system
  action      TEXT NOT NULL,                      -- auth.login | proposal.approve | event.create | …
  object_type TEXT, object_id TEXT,
  detail      JSONB,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX audit_user_time_idx ON audit_logs (user_id, created_at);
```

### Integrations & jobs

```sql
CREATE TABLE integrations (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id               UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider              TEXT NOT NULL,            -- google_calendar | gmail
  status                TEXT NOT NULL DEFAULT 'not_configured',
  encrypted_credentials TEXT,                     -- Fernet(envelope) — see SECURITY.md
  scopes                JSONB NOT NULL DEFAULT '[]',
  last_synced_at        TIMESTAMPTZ,
  sync_cursor           JSONB,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, provider)
);

CREATE TABLE jobs (
  id              BIGSERIAL PRIMARY KEY,
  user_id         UUID,
  type            TEXT NOT NULL,                  -- ingest_document | recompute_plan | trigger_deadline | …
  payload         JSONB NOT NULL,
  idempotency_key TEXT UNIQUE,                    -- dedupe across retries & triggers
  status          job_status NOT NULL DEFAULT 'pending',
  run_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  attempts        SMALLINT NOT NULL DEFAULT 0,
  max_attempts    SMALLINT NOT NULL DEFAULT 3,
  last_error      TEXT,
  claimed_at      TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX jobs_ready_idx ON jobs (status, run_at);

CREATE TABLE review_items (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind       TEXT NOT NULL,                       -- deadline | task | commitment | relationship
  question   TEXT NOT NULL,                       -- human-facing question
  payload    JSONB NOT NULL,                      -- what was extracted + alternatives
  status     review_status NOT NULL DEFAULT 'open',
  resolution JSONB,                               -- user's decision
  provenance JSONB NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX review_user_status_idx ON review_items (user_id, status);
```

## 4. Vector design

| Column | Dim | Model | Index | Purpose |
|---|---|---|---|---|
| `document_chunks.embedding` | 384 | bge-small-en-v1.5 (fastembed) | HNSW cosine | semantic retrieval |
| `entities.embedding` | 384 | same | exact scan (small N) | entity resolution matching |
| `memories.embedding` | 384 | same | exact scan | semantic memory recall |

One embedding model for all purposes keeps the pipeline cacheable and swap-safe. Dimension is
configurable at bootstrap only (changing it requires reindex migration — documented).

## 5. Temporal & provenance model

- `deadlines` keep `raw_expression` (verbatim), `normalized_at` (timestamptz or NULL),
  `date_is_exact`, `timezone`, `confidence`, `explicit`, `status`, `provenance`.
- Relative expressions resolve against the document's dates (`provenance.document_date`)
  or receipt time — always recorded alongside, so re-resolution is possible.
- Two deadlines for the same project/title with different dates → conflict surfaced as a
  review item; newer/more-authoritative source wins only after confirmation, never silently.
- Provenance JSONB shape (validated by pydantic in code):
  `{document_id, chunk_id?, page?, quote?, extractor, extracted_at, document_date?}`.

## 6. Retention & lifecycle

- `sessions` expire; pruned on access.
- `memories` decay: `expires_at` set from importance × recency; a maintenance job archives
  (not deletes) expired episodic memories for 90 days.
- `jobs` done/dead rows older than 30 days are pruned.
- Account deletion cascades everything from `users`; files under `data/<user_id>/` removed.
  Export = full JSON dump endpoint (documents metadata, entities, tasks, events, decisions).
