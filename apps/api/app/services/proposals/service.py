"""Action proposals: the wall between AI output and side effects.

Lifecycle: pending → approved/modified/rejected → executed/failed.
Executors validate typed payloads (pydantic), run Policy.check, mutate inside
one transaction, and write action_executions + audit rows (AI_SYSTEM.md, SECURITY.md §4).
"""

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Literal, TypeVar

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.models import ActionExecution, ActionProposal, AuditLog, Event, Goal, Note, Task, User
from app.models.enums import EventKind, GoalHorizon, ProposalStatus, RiskLevel
from app.services.policy import check as policy_check

logger = logging.getLogger("secondbrain.proposals")

T = TypeVar("T", bound=BaseModel)


class CreateEventPayload(BaseModel):
    title: str
    starts_at: datetime
    ends_at: datetime
    kind: str = "focus"
    reason: str = ""
    task_id: uuid.UUID | None = None


class CreateTaskPayload(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    estimated_minutes: int | None = Field(default=None, ge=5, le=24 * 60)
    priority: int = Field(default=3, ge=1, le=5)


class CreateNotePayload(BaseModel):
    title: str
    content: str


def _emails(values: list[str]) -> list[str]:
    from app.services.integrations.google import valid_email

    cleaned = [v.strip() for v in values]
    bad = [v for v in cleaned if not valid_email(v)]
    if bad:
        raise ValueError(f"invalid email address: {bad[0]!r}")
    return cleaned


class CreateMeetingPayload(BaseModel):
    provider: Literal["google_meet", "zoom", "apple_calendar"] = "google_meet"
    title: str = Field(min_length=1, max_length=300)
    starts_at: AwareDatetime  # naive times would mean three different zones across providers
    ends_at: AwareDatetime
    attendees: list[str] = Field(default_factory=list, max_length=50)
    # Attendees are added either way; they are only EMAILED when this is true.
    send_invites: bool = False
    description: str = Field(default="", max_length=5000)

    _v_attendees = field_validator("attendees")(_emails)

    @model_validator(mode="after")
    def _end_after_start(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if self.send_invites and self.provider != "google_meet":
            raise ValueError("only Google Meet can email invites")
        return self


class CreateEmailDraftPayload(BaseModel):
    provider: Literal["gmail", "apple_mail"] = "gmail"
    to: list[str] = Field(min_length=1, max_length=50)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(max_length=20000)

    _v_to = field_validator("to")(_emails)

    @field_validator("subject")
    @classmethod
    def _no_header_injection(cls, v: str) -> str:
        if "\r" in v or "\n" in v:
            raise ValueError("subject must be a single line")
        return v


class CreateReminderPayload(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    due_at: AwareDatetime | None = None
    list_name: str = Field(default="Reminders", min_length=1, max_length=100)
    notes: str = Field(default="", max_length=2000)


class CreateGoalPayload(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    why: str = Field(default="", max_length=300)
    horizon: GoalHorizon = GoalHorizon.week
    metric: str = Field(default="tasks", min_length=1, max_length=50)
    unit: str = Field(default="tasks", min_length=1, max_length=50)
    target_value: float = Field(gt=0, le=10000)
    starts_on: date
    due_on: date

    @model_validator(mode="after")
    def _due_not_before_start(self):
        if self.due_on < self.starts_on:
            raise ValueError("due_on must not be before starts_on")
        return self


class RunShortcutPayload(BaseModel):
    name: str = Field(min_length=1, max_length=200)


PAYLOAD_SCHEMAS: dict[str, type[BaseModel]] = {
    "create_event": CreateEventPayload,
    "create_task": CreateTaskPayload,
    "create_note": CreateNotePayload,
    "create_meeting": CreateMeetingPayload,
    "create_email_draft": CreateEmailDraftPayload,
    "create_reminder": CreateReminderPayload,
    "run_shortcut": RunShortcutPayload,
    "create_goal": CreateGoalPayload,
}

# Which policy action each proposal type needs.
PROPOSAL_POLICY_ACTION = {
    "create_event": "event.write_soft",  # hard events raise to event.write_hard below
    "create_task": "task.create",
    "create_note": "note.create",
    "create_meeting": "event.write_hard",  # + "meeting.invite" when send_invites
    "create_email_draft": "email.draft",
    "create_reminder": "task.create",
    "run_shortcut": "shortcut.run",
    "create_goal": "goal.write",
}

# Outward-facing actions: never part of a batch approval — one explicit decision each.
INDIVIDUAL_ONLY = {"create_meeting", "create_email_draft", "run_shortcut"}


def _external_policy_ok(user: User, payload: BaseModel) -> None:
    """Enforce autonomy level at EXECUTION for actions that leave the app."""
    if isinstance(payload, CreateMeetingPayload):
        # Emailing invitees is gated by the explicit, high-risk approval itself (the
        # danger list always allows-with-confirmation, so it adds no level check here).
        needed = ["event.write_hard"]
    elif isinstance(payload, CreateEmailDraftPayload):
        needed = ["email.draft"]
    elif isinstance(payload, CreateReminderPayload):
        needed = ["task.create"]
    elif isinstance(payload, RunShortcutPayload):
        needed = ["shortcut.run"]
    else:  # pragma: no cover
        raise PermissionError("no policy for this action")
    for action in needed:
        decision = policy_check(user, action)
        if not decision.allowed:
            raise PermissionError(decision.reason)


def _book_meeting(db, user: User, proposal: ActionProposal, p: CreateMeetingPayload) -> dict:
    """Create the meeting with its provider. Returns what the local Event needs.

    Attendees only reach a provider when invites are really being sent (Google Meet with
    send_invites). Otherwise they are listed in the description, so nobody is notified or
    dropped onto a calendar without consent, and nothing is silently lost."""
    emailing = p.provider == "google_meet" and p.send_invites and bool(p.attendees)
    description = p.description
    if p.attendees and not emailing:
        description = (description + "\n\n" if description else "") + "Invitees (not emailed): " + ", ".join(p.attendees)
    if p.provider == "google_meet":
        from app.services.integrations import google

        made = google.create_meet_event(
            db,
            user,
            title=p.title,
            starts_at=p.starts_at,
            ends_at=p.ends_at,
            attendees=p.attendees if emailing else [],
            description=description,
            send_invites=emailing,
            request_id=proposal.id.hex,
        )
        return {"provider": "google", "id": made["google_event_id"], "url": made["meet_url"]}
    if p.provider == "zoom":
        from app.services.integrations import zoom

        made = zoom.create_meeting(
            topic=p.title[:200],  # Zoom's limits are tighter than ours
            starts_at=p.starts_at,
            duration_minutes=int((p.ends_at - p.starts_at).total_seconds() // 60),
            timezone=user.timezone,
            agenda=description[:2000],
        )
        return {"provider": "zoom", "id": made["zoom_meeting_id"], "url": made["join_url"]}
    from app.services.integrations import apple

    made = apple.create_calendar_event(
        title=p.title, starts_at=p.starts_at, ends_at=p.ends_at, notes=description
    )
    return {"provider": "apple", "id": made["event_uid"], "url": None}


def _risk_for(action_type: str, validated: BaseModel, base: str) -> str:
    """Risk shown to the user; recomputed whenever the payload changes."""
    if action_type == "create_event" and validated.kind == EventKind.hard.value:
        return RiskLevel.high.value
    if isinstance(validated, CreateMeetingPayload):
        loud = validated.send_invites and validated.attendees
        return RiskLevel.high.value if loud else RiskLevel.medium.value
    if isinstance(validated, CreateEmailDraftPayload):
        return RiskLevel.medium.value
    if isinstance(validated, RunShortcutPayload):
        return RiskLevel.high.value  # a Shortcut can do anything
    return base


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
    risk_level = _risk_for(action_type, validated, risk_level)
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
        db.add(
            AuditLog(
                user_id=user.id,
                actor="user",
                action="proposal.reject",
                object_type="proposal",
                object_id=str(proposal.id),
            )
        )
        db.commit()
        return proposal
    if decision == "approve":
        proposal.status = ProposalStatus.approved
    elif decision == "modify":
        schema = PAYLOAD_SCHEMAS[proposal.action_type]
        validated = schema.model_validate(modified_payload or {})
        proposal.payload = validated.model_dump(mode="json")
        proposal.risk_level = RiskLevel(
            _risk_for(proposal.action_type, validated, proposal.risk_level.value)
        )
        proposal.status = ProposalStatus.modified
    else:
        raise ValueError(f"Unknown decision: {decision}")
    db.add(
        AuditLog(
            user_id=user.id,
            actor="user",
            action=f"proposal.{decision}",
            object_type="proposal",
            object_id=str(proposal.id),
        )
    )
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
                if payload.task_id and existing.task_id is None:
                    existing.task_id = payload.task_id
                result = {"event_id": str(existing.id), "duplicate": True}
            else:
                event = Event(
                    user_id=user.id,
                    kind=EventKind(payload.kind),
                    title=payload.title,
                    starts_at=payload.starts_at,
                    ends_at=payload.ends_at,
                    timezone=user.timezone,
                    provider="local",
                    editable=True,
                    task_id=payload.task_id,
                    source_proposal_id=proposal.id,
                    provenance={"proposal_id": str(proposal.id), "reason": proposal.reason},
                )
                db.add(event)
                db.flush()
                result = {"event_id": str(event.id)}
            if payload.task_id:
                task = db.get(Task, payload.task_id)
                if task is not None and task.user_id == user.id:
                    from app.models.enums import TaskStatus

                    task.status = TaskStatus.scheduled
        elif isinstance(payload, CreateTaskPayload):
            task = Task(
                user_id=user.id,
                title=payload.title,
                description=payload.description,
                estimated_minutes=payload.estimated_minutes,
                priority=payload.priority,
                provenance={"proposal_id": str(proposal.id), "reason": proposal.reason},
            )
            db.add(task)
            result = {"task_id": str(task.id)}
        elif isinstance(payload, CreateNotePayload):
            note = Note(
                user_id=user.id,
                title=payload.title,
                content=payload.content,
                provenance={"proposal_id": str(proposal.id)},
            )
            db.add(note)
            result = {"note_id": str(note.id)}
        elif isinstance(payload, CreateMeetingPayload):
            _external_policy_ok(user, payload)
            existing = db.execute(
                select(Event).where(Event.source_proposal_id == proposal.id)
            ).scalar_one_or_none()
            if existing is not None:  # re-run after a partial failure: don't double-create
                result = {"event_id": str(existing.id), "duplicate": True}
            else:
                made = _book_meeting(db, user, proposal, payload)
                event = Event(
                    user_id=user.id,
                    kind=EventKind.hard,
                    title=payload.title,
                    starts_at=payload.starts_at,
                    ends_at=payload.ends_at,
                    timezone=user.timezone,
                    location=made["url"],
                    description=payload.description or None,
                    provider=made["provider"],
                    provider_event_id=made["id"],
                    editable=True,
                    source_proposal_id=proposal.id,
                    provenance={"proposal_id": str(proposal.id), "reason": proposal.reason},
                )
                db.add(event)
                db.flush()
                result = {
                    "event_id": str(event.id),
                    "meeting_url": made["url"],
                    "invites_sent": bool(payload.send_invites and payload.attendees),
                }
        elif isinstance(payload, CreateEmailDraftPayload):
            _external_policy_ok(user, payload)
            if payload.provider == "apple_mail":
                from app.services.integrations import apple

                apple.create_mail_draft(to=payload.to, subject=payload.subject, body=payload.body)
                result = {"saved": True, "sent": False}
            else:
                from app.services.integrations import google

                made = google.create_draft(
                    db, user, to=payload.to, subject=payload.subject, body=payload.body
                )
                result = {"draft_id": made["draft_id"], "sent": False}
        elif isinstance(payload, CreateReminderPayload):
            _external_policy_ok(user, payload)
            from app.services.integrations import apple

            result = apple.create_reminder(
                title=payload.title,
                due_at=payload.due_at,
                list_name=payload.list_name,
                notes=payload.notes,
            )
        elif isinstance(payload, CreateGoalPayload):
            decision = policy_check(user, "goal.write")
            if not decision.allowed:
                raise PermissionError(decision.reason)
            existing = (
                db.execute(
                    select(Goal).where(
                        Goal.user_id == user.id,
                        Goal.title == payload.title,
                        Goal.starts_on == payload.starts_on,
                    )
                )
                .scalars()
                .first()
            )
            if existing is not None:
                result = {"goal_id": str(existing.id), "duplicate": True}
            else:
                goal = Goal(
                    user_id=user.id,
                    title=payload.title,
                    why=payload.why or None,
                    horizon=payload.horizon,
                    metric=payload.metric,
                    unit=payload.unit,
                    target_value=payload.target_value,
                    starts_on=payload.starts_on,
                    due_on=payload.due_on,
                    source=proposal.proposed_by,
                    provenance={"proposal_id": str(proposal.id), "reason": proposal.reason},
                )
                db.add(goal)
                db.flush()
                result = {"goal_id": str(goal.id)}
        elif isinstance(payload, RunShortcutPayload):
            _external_policy_ok(user, payload)
            from app.services.integrations import apple

            result = apple.run_shortcut(payload.name)
        else:  # pragma: no cover — schemas registry is exhaustive
            raise ValueError("no executor")
        proposal.executed_at = datetime.now(UTC)
        proposal.status = ProposalStatus.executed
        db.add(
            ActionExecution(
                proposal_id=proposal.id,
                user_id=user.id,
                status="success",
                result=result,
            )
        )
        db.add(
            AuditLog(
                user_id=user.id,
                actor=f"agent:{proposal.proposed_by}",
                action=f"proposal.execute.{proposal.action_type}",
                object_type="proposal",
                object_id=str(proposal.id),
                detail=result,
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        proposal.status = ProposalStatus.failed
        db.add(
            ActionExecution(
                proposal_id=proposal.id,
                user_id=user.id,
                status="failed",
                error=str(exc)[:1000],
            )
        )
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
