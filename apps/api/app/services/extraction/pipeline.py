"""Extraction pipeline: chunks → validated facts → knowledge/temporal writes.

Flow per document:
  1. injection scan (flags, never blocks analysis)
  2. classification pass (doc kind/title/topic/importance/summary)
  3. per-chunk structured extraction (dates, tasks, commitments, entities,
     relations) — every fact quote-verified against its chunk
  4. temporal normalization (deterministic) → deadlines; low confidence →
     review items, never confirmed
  5. tasks/commitments written; vague ones queued for review
  6. entity resolution + graph writes in the same transaction
  7. conflict detection against existing deadlines

The LLM proposes; deterministic code disposes. No LLM output reaches the
database without passing schema + quote + confidence gates.
"""

import logging
import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as OrmSession

from app.agents.prompts import (
    CLASSIFY_SYSTEM,
    EXTRACT_SYSTEM,
    PROMPT_VERSIONS,
    classify_user,
    dates_user,
    entities_user,
    tasks_user,
)
from app.agents.router import get_router
from app.models import (
    Commitment,
    Deadline,
    Document,
    ReviewItem,
    Task,
)
from app.models.enums import CommitmentConfidence, DeadlineStatus, DocumentStatus
from app.services.extraction.injection import detect_injection
from app.services.extraction.schemas import DocumentProfile
from app.services.extraction.verify import quote_in_text
from app.services.ingestion.lineage import record_derivation
from app.services.knowledge.resolution import KnowledgeService, coerce_kind, provenance_for
from app.services.temporal.normalizer import CONFIRM_THRESHOLD, normalize_when

logger = logging.getLogger("secondbrain.extraction")

MAX_EXTRACT_CHUNKS = 40
DOC_KINDS = "syllabus|lecture_slides|assignment|exam|meeting_notes|schedule|email_export|certificate|competition|notes|reference|other"


class ChunkExtraction(BaseModel):
    """Combined per-chunk payload — one LLM call per chunk (token efficiency)."""

    dates: list[dict] = Field(default_factory=list)
    tasks: list[dict] = Field(default_factory=list)
    commitments: list[dict] = Field(default_factory=list)
    entities: list[dict] = Field(default_factory=list)
    relations: list[dict] = Field(default_factory=list)


def _extract_chunk(db, router, document, chunk) -> ChunkExtraction:
    """One structured call pulling all fact types from one chunk."""
    user_prompt = (
        f"{dates_user(chunk.text)}\n\n"
        f"{tasks_user(chunk.text)}\n\n"
        f"{entities_user(chunk.text)}\n\n"
        "Submit ALL results in one `submit` call with keys: "
        "dates, tasks, commitments, entities, relations."
    )
    result = router.client.structured(
        model=router.model_for("extraction"),
        agent="inbox",
        purpose="extraction",
        system=EXTRACT_SYSTEM,
        user=user_prompt,
        schema_model=ChunkExtraction,
        db=db,
        user_id=document.user_id,
    )
    return result


def _review(db, user_id, kind: str, question: str, payload: dict, provenance: dict) -> None:
    # Dedupe: one open review item per kind+question (Week N spam guard).
    existing = (
        db.query(ReviewItem)
        .filter(
            ReviewItem.user_id == user_id,
            ReviewItem.kind == kind,
            ReviewItem.status == "open",
            ReviewItem.question == question,
        )
        .first()
    )
    if existing is not None:
        record_derivation(
            db, uuid.UUID(provenance["document_id"]), "review", existing.id, provenance
        )
        return
    review = ReviewItem(
        user_id=user_id, kind=kind, question=question, payload=payload, provenance=provenance
    )
    db.add(review)
    db.flush()
    record_derivation(db, uuid.UUID(provenance["document_id"]), "review", review.id, provenance)


_MONTH_WORDS = {
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
}


def _title_tokens(title: str) -> tuple[set[str], set[str]]:
    """Returns (word tokens, numeric tokens). Month names are dropped so two
    date-expressions like 'October 20' vs 'October 13' don't look like the
    same item; numbers are kept separate to distinguish Assignment 4 vs 3."""
    from app.services.knowledge.resolution import normalize_name

    stop = {
        "the",
        "a",
        "an",
        "of",
        "for",
        "to",
        "and",
        "in",
        "on",
        "due",
        "deadline",
        "submit",
        "week",
    }
    words: set[str] = set()
    numbers: set[str] = set()
    for token in normalize_name(title).split():
        if token in stop or token in _MONTH_WORDS:
            continue
        if token.isdigit():
            if len(token) == 4 and token.startswith(("19", "20")):
                continue  # years are not distinguishing
            numbers.add(token)
        else:
            words.add(token)
    return words, numbers


def _detect_deadline_conflicts(db, deadline: Deadline, provenance: dict) -> None:
    """Same-title deadline with a materially different date → review item.

    Matched by title-token overlap across the user's deadlines — a conflicting
    email may not carry the project context the syllabus had. Only called for
    deadlines that resolved to a concrete date.
    """
    candidates = (
        db.query(Deadline)
        .filter(
            Deadline.user_id == deadline.user_id,
            Deadline.id != deadline.id,
            Deadline.status != "rejected",
            Deadline.normalized_at.isnot(None),
        )
        .all()
    )
    tokens, numbers = _title_tokens(deadline.title)
    if not tokens:
        return  # pure date expressions never conflict-match by title
    for other in candidates:
        other_tokens, other_numbers = _title_tokens(other.title)
        overlap = tokens & other_tokens
        # Majority of the smaller title's words must match, and distinguishing
        # numbers must be consistent ("Assignment 4" ≠ "Assignment 3").
        if not overlap or len(overlap) < max(1, min(len(tokens), len(other_tokens))) * 0.5:
            continue
        if numbers and other_numbers and numbers != other_numbers:
            continue
        delta = abs((other.normalized_at - deadline.normalized_at).total_seconds())
        if delta > 24 * 3600:
            _review(
                db,
                deadline.user_id,
                "deadline_conflict",
                f"Deadline conflict detected: '{deadline.title}' has dates "
                f"{deadline.normalized_at.date()} and {other.normalized_at.date()} "
                f"from different sources. Which is correct?",
                {
                    "deadlines": [
                        {
                            "id": str(deadline.id),
                            "title": deadline.title,
                            "date": deadline.normalized_at.isoformat(),
                            "source": provenance,
                        },
                        {
                            "id": str(other.id),
                            "title": other.title,
                            "date": other.normalized_at.isoformat(),
                            "source": other.provenance,
                        },
                    ]
                },
                provenance,
            )
            break


def extract_document(db: OrmSession, document: Document, chunks) -> Document:
    from app.models import User

    router = get_router()
    knowledge = KnowledgeService(db)
    user = db.get(User, document.user_id)
    user_timezone = user.timezone if user else "Asia/Jakarta"

    document.status = DocumentStatus.extracting
    db.commit()

    # --- 1. Injection scan ---
    full_text = "\n".join(c.text for c in chunks)
    injection_flags = detect_injection(full_text)

    # --- 2. Classification ---
    profile = router.client.structured(
        model=router.model_for("classify"),
        agent="inbox",
        purpose="classify",
        system=CLASSIFY_SYSTEM,
        user=classify_user(full_text[:1500], DOC_KINDS),
        schema_model=DocumentProfile,
        db=db,
        user_id=document.user_id,
    )
    from app.models.enums import DocumentKind

    kind_values = {k.value for k in DocumentKind}
    document.doc_kind = (
        DocumentKind(profile.doc_kind) if profile.doc_kind in kind_values else DocumentKind.other
    )
    document.title = profile.title or document.title
    document.topic = profile.topic or None
    document.summary = profile.summary or None
    document.importance = profile.importance
    db.commit()

    # --- 2b. Injection quarantine (SECURITY.md §9.3) ---
    # A flagged document's facts never enter the knowledge base or planner
    # directly: they are quarantined for human review. Analysis continues only
    # after the user resolves the review item.
    if injection_flags:
        _review(
            db,
            document.user_id,
            "injection",
            "This document contains instruction-like content attempting to steer the AI "
            "(possible prompt injection). It was treated strictly as data and quarantined: "
            "no deadlines, tasks, or entities were created from it. Review?",
            {"flags": injection_flags, "document_id": str(document.id)},
            provenance_for(document),
        )
        document.provenance = {
            "extraction_done": True,
            "quarantined": True,
            "prompt_versions": PROMPT_VERSIONS,
            "injection_flags": injection_flags,
        }
        document.status = DocumentStatus.processed
        document.processed_at = datetime.now(UTC)
        db.commit()
        return document

    # --- 3. Project inference (courses/competitions become projects) ---
    project = None
    if document.doc_kind in (
        DocumentKind.syllabus,
        DocumentKind.assignment,
        DocumentKind.exam,
        DocumentKind.competition,
        DocumentKind.lecture_slides,
    ):
        project_name = document.topic or document.title or document.original_filename
        project = knowledge.ensure_project(
            document.user_id,
            project_name,
            kind="course"
            if document.doc_kind
            in (
                DocumentKind.syllabus,
                DocumentKind.lecture_slides,
                DocumentKind.exam,
                DocumentKind.assignment,
            )
            else "project",
            provenance=provenance_for(document),
        )
        record_derivation(db, document.id, "project", project.id, provenance_for(document))
        record_derivation(db, document.id, "entity", project.entity_id, provenance_for(document))
        document.project_id = project.id
        db.commit()

    review_count = 0

    # --- 4-6. Per-chunk extraction → verified facts → writes ---
    for chunk in chunks[:MAX_EXTRACT_CHUNKS]:
        try:
            extraction = _extract_chunk(db, router, document, chunk)
        except Exception as exc:
            logger.warning(
                "chunk extraction failed: %s", exc, extra={"document_id": str(document.id)}
            )
            continue

        chunk_prov = provenance_for(document, chunk, extractor="inbox:v1")

        # Dates → deterministic normalization → deadlines
        for date_fact in extraction.dates:
            quote = str(date_fact.get("quote") or "")
            when_text = str(date_fact.get("when_text") or "")
            if not quote or not when_text or not quote_in_text(quote, chunk.text):
                continue
            title = str(date_fact.get("title") or "") or when_text
            # Dedupe across chunks/documents: same item + same raw expression
            # extracted again is the same fact, not a new one.
            duplicate = (
                db.query(Deadline)
                .filter(
                    Deadline.user_id == document.user_id,
                    Deadline.title == title[:300],
                    Deadline.raw_expression == when_text[:500],
                )
                .first()
            )
            if duplicate is not None:
                record_derivation(
                    db, document.id, "deadline", duplicate.id, {**chunk_prov, "quote": quote}
                )
                continue
            normalized = normalize_when(
                when_text,
                reference=document.created_at,
                tz_name=user_timezone,
            )
            deadline = Deadline(
                user_id=document.user_id,
                title=title[:300],
                normalized_at=normalized.normalized_at,
                date_is_exact=normalized.date_is_exact,
                raw_expression=when_text[:500],
                timezone=user_timezone,
                confidence=normalized.confidence,
                explicit=normalized.explicit,
                status=(
                    DeadlineStatus.confirmed
                    if normalized.confidence >= CONFIRM_THRESHOLD and normalized.explicit
                    else DeadlineStatus.tentative
                ),
                project_id=project.id if project else None,
                provenance={**chunk_prov, "quote": quote},
            )
            db.add(deadline)
            db.flush()
            record_derivation(db, document.id, "deadline", deadline.id, deadline.provenance)
            if normalized.needs_review and not normalized.is_recurrence:
                _review(
                    db,
                    document.user_id,
                    "deadline",
                    f"I found a possible date '{deadline.raw_expression}' for "
                    f"'{deadline.title}' but couldn't resolve it confidently "
                    f"({normalized.note or 'relative expression'}). What is the actual date?",
                    {
                        "deadline_id": str(deadline.id),
                        "title": deadline.title,
                        "raw_expression": deadline.raw_expression,
                    },
                    chunk_prov,
                )
                review_count += 1
            elif normalized.is_recurrence:
                _review(
                    db,
                    document.user_id,
                    "deadline",
                    f"'{deadline.raw_expression}' looks like a recurring schedule "
                    f"('{deadline.title}'). Add it as a recurring calendar event?",
                    {"deadline_id": str(deadline.id), "recurring": True},
                    chunk_prov,
                )
                review_count += 1
            else:
                _detect_deadline_conflicts(db, deadline, chunk_prov)

        # Tasks (title falls back to the quote — models sometimes omit it)
        for task_fact in extraction.tasks:
            quote = str(task_fact.get("quote") or "")
            if not quote or not quote_in_text(quote, chunk.text):
                continue
            title = str(task_fact.get("title") or "").strip() or quote.strip()[:120]
            task = Task(
                user_id=document.user_id,
                title=title[:300],
                description=quote[:1000],
                project_id=project.id if project else None,
                estimated_minutes=task_fact.get("estimated_minutes"),
                provenance={**chunk_prov, "quote": quote},
                confidence=0.6,
            )
            db.add(task)
            db.flush()
            record_derivation(db, document.id, "task", task.id, task.provenance or chunk_prov)

        # Commitments
        for commitment_fact in extraction.commitments:
            quote = str(commitment_fact.get("quote") or "")
            if not quote or not quote_in_text(quote, chunk.text):
                continue
            level = commitment_fact.get("confidence", "possible")
            confidence_enum = (
                CommitmentConfidence.confirmed
                if level == "confirmed"
                else CommitmentConfidence.likely
                if level == "likely"
                else CommitmentConfidence.possible
            )
            commitment = Commitment(
                user_id=document.user_id,
                text=str(commitment_fact.get("text") or quote)[:1000],
                direction=str(commitment_fact.get("direction") or "user_promised"),
                confidence=confidence_enum,
                provenance={**chunk_prov, "quote": quote},
            )
            db.add(commitment)
            db.flush()
            record_derivation(db, document.id, "commitment", commitment.id, commitment.provenance)

        # Entities + relations (knowledge graph)
        resolved: dict[str, object] = {}
        for entity_fact in extraction.entities:
            name = str(entity_fact.get("name") or "").strip()
            if not name:
                continue
            kind = coerce_kind(entity_fact.get("kind") or "topic")
            try:
                entity = knowledge.resolve(document.user_id, name, kind, provenance=chunk_prov)
                resolved[name.lower()] = entity
                record_derivation(db, document.id, "entity", entity.id, chunk_prov)
            except Exception:
                logger.exception("entity resolution failed for %r", name)
        for mention_name, entity in resolved.items():
            if mention_name and mention_name.lower() in chunk.text.lower():
                knowledge.add_mention(document.user_id, chunk, entity, mention_name, 0.7)
        for relation in extraction.relations:
            subject = resolved.get(str(relation.get("subject") or "").lower())
            object_ = resolved.get(str(relation.get("object") or "").lower())
            predicate = str(relation.get("predicate") or "").strip()
            relation_quote = str(relation.get("quote") or "")
            if subject is None or object_ is None or not predicate:
                continue
            if not relation_quote or not quote_in_text(relation_quote, chunk.text):
                continue
            linked = knowledge.link_relationship(
                document.user_id,
                subject,
                predicate,
                object_,
                0.7,
                {**chunk_prov, "quote": relation_quote},
            )
            if linked is not None:
                record_derivation(
                    db,
                    document.id,
                    "relationship",
                    linked.id,
                    {**chunk_prov, "quote": relation_quote},
                )

    # --- 7. Finalize ---
    document.provenance = {
        "extraction_done": True,
        "prompt_versions": PROMPT_VERSIONS,
        "review_items_created": review_count,
    }
    document.status = DocumentStatus.processed
    document.processed_at = datetime.now(UTC)
    db.commit()
    return document
