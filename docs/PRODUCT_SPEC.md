# Product Specification — Second Brain OS

Status: v1.0 · Owner: Willson · Last updated: 2026-09-02

## 1. Product vision

Second Brain OS is the **central intelligence layer between the user and their digital life**.
The user dumps raw material — PDFs, lecture slides, assignments, syllabi, schedules, emails,
links, notes, screenshots — and the system continuously converts that material into an
evolving, queryable model of the user's life: projects, courses, people, deadlines,
commitments, and knowledge. On top of that model it plans, prepares, and proposes action.

> The ultimate interaction: open the app, ask **"What should I do?"** — and get an
> exceptionally good, evidence-backed answer.

This is explicitly **not** a Notion clone, chatbot, file manager, or thin RAG app. It is an
agentic personal operating system whose core asset is a structured, provenance-tracked
knowledge + temporal model of the user's responsibilities.

## 2. Product principles

1. **Drop in, trust the system.** The AI infers structure; the user never files or tags manually.
2. **Calm interface.** High-value information over information density. No red-badge anxiety.
3. **Provenance or it didn't happen.** Every AI-derived fact links back to source (document, page, quote, confidence).
4. **Determinism where possible.** Scheduling, conflict detection, and date math are algorithms, not LLM output.
5. **Propose, don't act.** Consequential actions surface as reviewable proposals; sending/deleting always requires explicit approval.
6. **Data is not instructions.** Uploaded content can never steer agent behavior (injection-hardened by design and by test).
7. **Useful at rest.** The system prepares briefings, plans, and drafts *before* they're needed.
8. **Recover, don't scold.** When the user falls behind, generate the best recovery plan rather than displaying overdue red.

## 3. Users

Primary (and initially only) user: **the owner** — a university student / knowledge worker
who juggles courses, competitions, projects, email, and meetings; technically comfortable;
values privacy (local-first model defaults); wants to spend attention on work, not on
organizing work.

Single-tenant-by-design in MVP (self-hosted, one primary account), but the data model is
multi-user from day one (row-level `user_id` scoping) so hosted multi-tenancy is a config
change, not a rewrite.

## 4. Core loop

```
CAPTURE     drop files / sync email & calendar / paste links
UNDERSTAND  parse → segment → summarize → extract (typed, schema-validated)
ORGANIZE    classify, title, file under inferred projects/courses
CONNECT     entity resolution → knowledge graph (people, projects, concepts, dates)
PRIORITIZE  attention engine scores urgency × importance × risk × readiness
PLAN        deterministic scheduler maps tasks onto real calendar availability
PREPARE     briefings: pre-class, pre-meeting, pre-exam, pre-competition
ACT         proposals (calendar blocks, drafts, tasks) → approve/modify/reject
REFLECT     what happened, what slipped, what was completed
LEARN       memory layers update preferences, estimates, and mastery
```

## 5. User experience

### 5.1 Primary navigation (5 surfaces)

| Surface  | Purpose |
|----------|---------|
| **HOME** | Morning briefing: today's schedule, top priorities, risks, AI suggestions (each with "Why?" evidence), upcoming 3/7/30 days. |
| **INBOX**| Drag-and-drop bulk upload; per-item processing status; review cards for low-confidence extractions awaiting confirmation. |
| **CALENDAR** | Week view distinguishing HARD EVENT / SOFT PLAN / DEADLINE / FOCUS BLOCK / REMINDER; proposal drawer with Approve/Modify/Reject and batch approval. |
| **BRAIN**| Knowledge graph browser: projects → courses → deadlines → people → documents; entity detail with provenance links to source page/quote. |
| **ASK**  | Natural-language command bar answering from structured state + retrieval, with citations. |

### 5.2 Secondary surfaces (contextual, not primary nav)

Projects, Study, Tasks, People, Mail (Phase 2+). These are deep-links reachable from BRAIN
and HOME rather than top-level destinations, keeping the interface calm.

### 5.3 Interaction contract

- Every AI suggestion shows its reasoning/evidence via a "Why?" affordance.
- Every consequential change is a proposal: `[Approve] [Modify] [Reject]`, batch-approvable.
- Low-confidence extractions never silently become commitments — they queue for review.

## 6. Major features

| Feature | Description |
|---|---|
| **Universal Inbox** | Bulk ingestion of PDF/DOCX/PPTX/XLSX/CSV/TXT/MD/images/URLs/ZIP; automatic type/title/topic/project/people/dates/importance/summary inference. |
| **Knowledge Graph** | Typed entities (Person, Course, Project, Organization, Event, Deadline, Task, Document, Email, Meeting, Goal, Topic, Concept, Commitment, Location) + relationships, backed by relational tables, embeddings, and provenance. Answers relational queries, not just similarity. |
| **Temporal Intelligence** | Normalizes expressions ("next Friday", "week 7", "before the midterm", "every Monday") preserving raw text, timezone, source, confidence, explicit-vs-inferred flag; detects conflicts and suspicious dates. |
| **Calendar Intelligence** | Google Calendar sync (creds-optional; .ics import fallback); free-time analysis; event kinds; preparation requirements. |
| **Dynamic Planning Engine** | Deterministic constraint scheduler (priorities, durations, dependencies, min session length, splittable tasks, buffers, preferred hours, cognitive load); automatic rescheduling when reality changes. |
| **Study Intelligence** (Phase 2 UI, schema in MVP) | Summaries, concepts, flashcards, likely exam questions, mastery model, spaced repetition. |
| **Event Preparation** | Auto briefings before class/meeting/interview/exam/competition. |
| **Email Intelligence** (Phase 2) | Gmail read, thread summaries, task/deadline extraction, drafts; send always gated. |
| **Daily Briefing** | The "what should I care about today" surface. |
| **Command Center (ASK)** | Tool-calling over structured state: "what am I behind on?", "prepare me for tomorrow", "show every commitment I made to John". |
| **Memory System** | Working / episodic / semantic / procedural layers with importance, confidence, and decay. |
| **Commitment Detection** | Obligation language ("I'll send it tomorrow") → Commitment objects with Confirmed/Likely/Possible confidence. |
| **Readiness Score** | For important events: material coverage, practice, weak concepts, time remaining — explained, never fake precision. |
| **Attention Engine** | urgency × importance × risk × effort × dependency × opportunity cost; explicitly not a deadline sort. |
| **Life Conflict Detector** | Two deadlines <24h apart, overloaded days, insufficient prep time, unanswered important email, missing prerequisite. |
| **Preparation Windows** | Events generate prep requirements (3h slides + 1h rehearsal + 30m review) automatically reserved. |
| **Recovery Planning** | "You're 4h behind" → best recovery plan preserving sleep, not a red overdue list. |
| **Action/Permission Architecture** | Levels 0–4 (Observer → Autonomous); dangerous actions always confirmation-gated; every action auditable. |
| **Decision Log** | AI decisions stored with reason + evidence, making the system debuggable and explainable. |

## 7. MVP boundary

The MVP proves the core loop end-to-end:

```
DROP INFORMATION → UNDERSTAND → CREATE KNOWLEDGE → DETECT TASKS/DEADLINES
→ PLAN CALENDAR → ASK QUESTIONS → PREPARE ACTIONS
```

**In scope (MVP):** authentication; universal file inbox; PDF/DOCX/PPTX/XLSX/CSV/TXT/MD parsing;
AI classification + extraction (typed, validated); Postgres knowledge model + pgvector RAG;
task/deadline/commitment extraction with review queue; Google Calendar adapter (creds-optional)
with .ics import + local calendar; deterministic scheduler + rescheduling; daily briefing
dashboard; ASK command bar; action proposal/approval system with audit log; decision log.

**Out of scope (MVP), scheduled later:** Gmail sync & email drafts (Phase 2); study UI +
mastery tracking UI (Phase 2, schema ships now); meeting minutes analysis (Phase 2);
autonomous execution Level 4 (Phase 3); graph force-layout visualization (Phase 3);
mobile (Phase 3); multi-user sharing/collaboration (never in current product thesis);
OCR of images (Phase 2 — image ingestion accepted and stored, text extraction later).

## 8. Non-goals

- **Not** a general-purpose note editor / wiki (no manual page trees).
- **Not** a team/collaboration tool.
- **Not** an auto-sending email bot — outbound actions stay human-approved.
- **Not** vendor-locked AI — the model layer is an OpenAI-compatible abstraction.
- **No** dark-pattern engagement mechanics; the product succeeds when the user spends *less* time in it.

## 9. Success criteria for MVP

1. Drop a syllabus-like PDF + assignment doc + meeting notes + .ics → system builds a course
   tree with deadlines, tasks, people; ambiguous dates remain tentative.
2. Ask "what's due next week?" → cited, correct answer from structured deadlines.
3. Exam Friday → planner proposes staged Mon–Thu focus blocks respecting real availability.
4. Deleting one focus session → plan recomputes without touching hard events.
5. A proposal (calendar block) can be approved, modified, rejected — each audited.
6. An uploaded document containing injection instructions produces zero agent actions (tested).
