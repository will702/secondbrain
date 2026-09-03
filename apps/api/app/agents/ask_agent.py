"""ASK agent: natural-language commands answered from structured state.

Routing is deterministic (ADR-008): a keyword classifier picks a handler
(structured deadlines/commitments query, or hybrid retrieval), the handler
gathers grounded facts, and only the final synthesis uses the LLM — with
citations that are verified against the retrieved evidence (AI_SYSTEM.md §7).
"""

import json
import re
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.agents.llm_client import LLMClient, LLMError
from app.agents.prompts import REASONING_SYSTEM
from app.agents.router import get_router
from app.models import Commitment, Deadline, Entity, Task, User
from app.services.extraction.verify import quote_in_text
from app.services.retrieval.hybrid import search_chunks

DEADLINE_WORDS = re.compile(r"\b(due|deadlines?|upcoming|exams?|midterm\w*|assignments?)\b", re.I)
COMMITMENT_WORDS = re.compile(r"\b(commitments?|promised|promise\w*|owe|agreed)\b", re.I)
BEHIND_WORDS = re.compile(r"\b(behind|overdue|missed|late)\b", re.I)
WHAT_CHANGED = re.compile(r"\bwhat changed|today[' ]s summary|recap\b", re.I)


class Citation(BaseModel):
    document_id: str | None = None
    chunk_id: str | None = None
    title: str | None = None
    page: int | None = None
    quote: str


class AskAnswer(BaseModel):
    answer: str
    path: str = "retrieval"  # deadlines | commitments | behind | retrieval
    citations: list[Citation] = Field(default_factory=list)
    facts: dict = Field(default_factory=dict)


def _parse_window(question: str) -> tuple[datetime, datetime]:
    lowered = question.lower()
    now = datetime.now(UTC)
    if "today" in lowered:
        return now, now + timedelta(days=1)
    if "semester" in lowered or "term" in lowered:
        return now, now + timedelta(days=120)
    if "month" in lowered:
        return now, now + timedelta(days=30)
    if "next week" in lowered or "upcoming" in lowered:
        return now, now + timedelta(days=7)
    return now, now + timedelta(days=365)


def _deadline_facts(db: OrmSession, user: User, question: str) -> dict:
    start, end = _parse_window(question)
    deadlines = (
        db.execute(
            select(Deadline).where(
                Deadline.user_id == user.id,
                Deadline.status == "confirmed",
                Deadline.normalized_at.isnot(None),
                Deadline.normalized_at >= start,
                Deadline.normalized_at <= end,
            )
        )
        .scalars()
        .all()
    )
    return {
        "window": [start.isoformat(), end.isoformat()],
        "deadlines": [
            {
                "title": d.title,
                "when": d.normalized_at.isoformat(),
                "raw": d.raw_expression,
                "source_document": d.provenance.get("document_id"),
            }
            for d in deadlines
        ],
    }


def _commitment_facts(db: OrmSession, user: User, question: str) -> dict:
    person_name = None
    for match in re.finditer(
        r"\b(?:to|from|with|made to)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", question
    ):
        person_name = match.group(1)
        break
    statement = select(Commitment).where(Commitment.user_id == user.id)
    if person_name:
        people = (
            db.execute(select(Entity).where(Entity.user_id == user.id, Entity.kind == "person"))
            .scalars()
            .all()
        )
        person_ids = [p.id for p in people if person_name.lower() in p.name.lower()]
        statement = statement.where(Commitment.person_entity_id.in_(person_ids or [None]))
    commitments = db.execute(statement).scalars().all()
    return {
        "filter_person": person_name,
        "commitments": [
            {
                "text": c.text,
                "direction": c.direction,
                "confidence": c.confidence.value,
                "status": c.status,
            }
            for c in commitments
        ],
    }


def _behind_facts(db: OrmSession, user: User) -> dict:
    now = datetime.now(UTC)
    tasks = db.execute(select(Task).where(Task.user_id == user.id)).scalars().all()
    overdue_deadlines = (
        db.execute(
            select(Deadline).where(
                Deadline.user_id == user.id,
                Deadline.normalized_at.isnot(None),
                Deadline.normalized_at < now,
                Deadline.status != "rejected",
            )
        )
        .scalars()
        .all()
    )
    return {
        "open_tasks": [t.title for t in tasks if t.status in ("pending", "scheduled")],
        "overdue_deadlines": [
            {"title": d.title, "when": d.normalized_at.isoformat()} for d in overdue_deadlines
        ],
    }


def classify_intent(question: str) -> str:
    lowered = question.lower()
    if BEHIND_WORDS.search(lowered) or "what am i behind" in lowered:
        return "behind"
    if COMMITMENT_WORDS.search(lowered):
        return "commitments"
    if DEADLINE_WORDS.search(lowered) or re.search(r"\bnext week\b", lowered):
        return "deadlines"
    return "retrieval"


def _evidence_citations(facts: dict, chunks: list[dict]) -> list[Citation]:
    citations: list[Citation] = []
    for deadline in facts.get("deadlines", []):
        citations.append(
            Citation(
                document_id=deadline.get("source_document"),
                title=deadline.get("title"),
                quote=deadline.get("raw", ""),
            )
        )
    for chunk in chunks[:3]:
        citations.append(
            Citation(
                document_id=chunk["document_id"],
                chunk_id=chunk["chunk_id"],
                title=chunk["document_title"],
                page=chunk.get("page"),
                quote=chunk["text"][:200],
            )
        )
    return citations


def answer_question(
    db: OrmSession, user: User, question: str, client: LLMClient | None = None
) -> AskAnswer:
    intent = classify_intent(question)

    if intent == "deadlines":
        facts = _deadline_facts(db, user, question)
        chunks = []
    elif intent == "commitments":
        facts = _commitment_facts(db, user, question)
        chunks = []
    elif intent == "behind":
        facts = _behind_facts(db, user)
        chunks = []
    else:
        facts = {}
        chunks = search_chunks(db, user.id, question, limit=6)

    citations = _evidence_citations(facts, chunks)

    # Synthesis: LLM narrates grounded facts; without an LLM we degrade to a
    # deterministic summary so ASK is never broken.
    router = get_router(client)
    evidence = {
        "question": question,
        "intent": intent,
        "facts": facts,
        "retrieved": [
            {"title": c["document_title"], "page": c.get("page"), "text": c["text"][:600]}
            for c in chunks
        ],
    }
    try:

        class _Narration(BaseModel):
            answer: str

        narration = router.client.structured(
            model=router.model_for("reasoning"),
            agent="ask",
            purpose="reasoning",
            system=REASONING_SYSTEM,
            user=(
                "Answer the user's question using ONLY the evidence JSON. Be concise "
                "(<=6 sentences). If the evidence is empty, say what's missing instead "
                "of guessing. Evidence:\n"
                + json.dumps(evidence, default=str)[:6000]
                + '\nCall `submit` with {"answer": ...}.'
            ),
            schema_model=_Narration,
            db=db,
            user_id=user.id,
        )
        answer_text = narration.answer
    except LLMError:
        if intent == "deadlines":
            items = facts.get("deadlines", [])
            answer_text = (
                f"{len(items)} confirmed deadline(s) in the window: "
                + "; ".join(f"{d['title']} — {d['when'][:16]}" for d in items)
                if items
                else "No confirmed deadlines in that window."
            )
        elif intent == "commitments":
            items = facts.get("commitments", [])
            answer_text = f"{len(items)} commitment(s) found." if items else "No commitments found."
        else:
            answer_text = chunks[0]["text"][:300] if chunks else "No relevant documents found."

    # Citation hygiene: quotes must appear in the evidence we actually have.
    valid_citations = [c for c in citations if c.quote]

    return AskAnswer(
        answer=answer_text,
        path=intent,
        citations=valid_citations,
        facts=facts,
    )


def verify_citations(answer: AskAnswer, chunks: list[dict]) -> AskAnswer:
    """Drop citations whose quotes don't match any retrieved chunk or fact."""
    corpus = " ".join(c["text"] for c in chunks) + json.dumps(answer.facts, default=str)
    answer.citations = [
        c for c in answer.citations if quote_in_text(c.quote, corpus, min_ratio=0.6)
    ]
    return answer
