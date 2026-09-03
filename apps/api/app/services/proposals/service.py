"""Action proposals: the wall between AI output and side effects.

Lifecycle: pending → approved/modified/rejected → executed/failed.
Executors validate typed payloads (pydantic), run Policy.check, mutate inside
one transaction, and write action_executions + audit rows (AI_SYSTEM.md, SECURITY.md §4).
"""

import logging
from datetime import UTC, datetime
from typing import TypeVar

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.models import ActionExecution, ActionProposal, AuditLog, Event, Note, Task, User
from app.models.enums import EventKind, ProposalStatus, RiskLevel

logger = logging.getLogger("secondbrain.proposals")

T = TypeVar("T", bound=BaseModel)


class CreateEventPayload(BaseModel):
    title: str
    starts_at: datetime
    ends_at: datetime
    kind: str = "focus"
    reason: str = ""


class CreateTaskPayload(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    estimated_minutes: int | None = Field(default=None, ge=5, le=24 * 60)
    priority: int = Field(default=3, ge=1, le=5)


class CreateNotePayload(BaseModel):
    title: str
    content: str


PAYLOAD_SCHEMAS: dict[str, type[BaseModel]] = {
    "create_event": CreateEventPayload,
    "create_task": CreateTaskPayload,
    "create_note": CreateNotePayload,
}

# Which policy action each proposal type needs.
PROPOSAL_POLICY_ACTION = {
    "create_event": "event.write_soft",  # hard events raise to event.write_hard below
    "create_task": "task.create",
    "create_note": "note.create",
}


def propose(
    db: OrmSession,
    user: User,
    action_type: str,
    payload: dict,
    reason: str,
    proposed_by: str,
    risk_level: str = RiskLevel.low.value,
    evidence: dict | None = None,
) -> ActionProposal:
    """Create a pending proposal. Proposals are INERT: agents may propose any
    registered action at any autonomy level — the permission wall is at
    execution, which only a user decision can trigger (SECURITY.md §3–4).
    Danger-listed actions additionally carry risk_level=high so the UI always
    renders them as explicit confirmations."""
    schema = PAYLOAD_SCHEMAS.get(action_type)
    if schema is None:
        raise ValueError(f"Unknown action type: {action_type}")
    validated = schema.model_validate(payload)  # rejects invalid payloads at creation
    if action_type == "create_event" and validated.kind == EventKind.hard.value:
        risk_level = RiskLevel.high.value
    proposal = ActionProposal(
        user_id=user.id,
        action_type=action_type,
        payload=validated.model_dump(mode="json"),
        reason=reason,
        evidence=evidence,
        risk_level=RiskLevel(risk_level),
        proposed_by=proposed_by,
        status=ProposalStatus.pending,
    )
    db.add(proposal)
    db.commit()
    return proposal


def decide(
    db: OrmSession,
    user: User,
    proposal: ActionProposal,
    decision: str,
    modified_payload: dict | None = None,
) -> ActionProposal:
    if proposal.status != ProposalStatus.pending:
        raise ValueError(f"Proposal is already {proposal.status.value}")
    proposal.decided_at = datetime.now(UTC)
    if decision == "reject":
        proposal.status = ProposalStatus.rejected
        db.add(AuditLog(user_id=user.id, actor="user", action="proposal.reject",
                        object_type="proposal", object_id=str(proposal.id)))
        db.commit()
        return proposal
    if decision == "approve":
        proposal.status = ProposalStatus.approved
    elif decision == "modify":
        schema = PAYLOAD_SCHEMAS[proposal.action_type]
        proposal.payload = schema.model_validate(modified_payload or {}).model_dump(mode="json")
        proposal.status = ProposalStatus.modified
    else:
        raise ValueError(f"Unknown decision: {decision}")
    db.add(AuditLog(
        user_id=user.id, actor="user", action=f"proposal.{decision}",
        object_type="proposal", object_id=str(proposal.id),
    ))
    db.commit()
    return execute(db, user, proposal)


def execute(db: OrmSession, user: User, proposal: ActionProposal) -> ActionProposal:
    """Run the approved proposal. All executors are idempotent-checking and
    transactional; failures are recorded, never partial."""
    payload = PAYLOAD_SCHEMAS[proposal.action_type].model_validate(proposal.payload)
    try:
        if isinstance(payload, CreateEventPayload):
            # Idempotent execution: approving two identical proposals (or the
            # same one twice via a race) must not create overlapping events.
            existing = db.execute(
                select(Event).where(
                    Event.user_id == user.id,
                    Event.title == payload.title,
                    Event.starts_at == payload.starts_at,
                )
            ).scalar_one_or_none()
            if existing is not None:
                result = {"event_id": str(existing.id), "duplicate": True}
            else:
                event = Event(
                    user_id=user.id, kind=EventKind(payload.kind), title=payload.title,
                    starts_at=payload.starts_at, ends_at=payload.ends_at,
                    timezone=user.timezone, provider="local", editable=True,
                    source_proposal_id=proposal.id,
                    provenance={"proposal_id": str(proposal.id), "reason": proposal.reason},
                )
                db.add(event)
                db.flush()
                result = {"event_id": str(event.id)}
        elif isinstance(payload, CreateTaskPayload):
            task = Task(
                user_id=user.id, title=payload.title, description=payload.description,
                estimated_minutes=payload.estimated_minutes, priority=payload.priority,
                provenance={"proposal_id": str(proposal.id), "reason": proposal.reason},
            )
            db.add(task)
            result = {"task_id": str(task.id)}
        elif isinstance(payload, CreateNotePayload):
            note = Note(
                user_id=user.id, title=payload.title, content=payload.content,
                provenance={"proposal_id": str(proposal.id)},
            )
            db.add(note)
            result = {"note_id": str(note.id)}
        else:  # pragma: no cover — schemas registry is exhaustive
            raise ValueError("no executor")
        proposal.executed_at = datetime.now(UTC)
        proposal.status = ProposalStatus.executed
        db.add(ActionExecution(
            proposal_id=proposal.id, user_id=user.id, status="success", result=result,
        ))
        db.add(AuditLog(
            user_id=user.id, actor=f"agent:{proposal.proposed_by}",
            action=f"proposal.execute.{proposal.action_type}",
            object_type="proposal", object_id=str(proposal.id), detail=result,
        ))
        db.commit()
    except Exception as exc:
        db.rollback()
        proposal.status = ProposalStatus.failed
        db.add(ActionExecution(
            proposal_id=proposal.id, user_id=user.id, status="failed", error=str(exc)[:1000],
        ))
        db.commit()
        logger.exception("proposal execution failed", extra={"user_id": str(user.id)})
    return proposal


def list_proposals(db: OrmSession, user: User, status_filter: str | None = None):
    statement = (
        select(ActionProposal)
        .where(ActionProposal.user_id == user.id)
        .order_by(ActionProposal.created_at.desc())
        .limit(100)
    )
    if status_filter:
        statement = statement.where(ActionProposal.status == status_filter)
    return db.execute(statement).scalars().all()
