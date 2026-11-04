"""Quick-command parser: one typed sentence -> ONE inert proposal.

The local `fast` model only extracts intent; dates go through the deterministic
temporal normalizer; the result is a proposal the user must still approve.
Nothing here sends, books or writes anything outside the proposals table.
"""

from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session as OrmSession

from app.agents.router import ModelRouter, get_router
from app.models import ActionProposal, User
from app.services.integrations.google import valid_email
from app.services.proposals.service import propose
from app.services.temporal.normalizer import normalize_when, utcnow

MAX_COMMAND_CHARS = 500

SYSTEM = (
    "You turn one short user command into structured intent. Choose intent: "
    "meeting (schedule a call/meeting), email_draft (write an email), task (a to-do), "
    "reminder (remind me at a time), note (remember something), or unknown. Copy the date/time phrase verbatim into "
    "when_text; never compute dates. Only include email addresses that appear verbatim "
    "in the command; never invent addresses. Set wants_zoom only if the user says Zoom."
)


class QuickIntent(BaseModel):
    intent: Literal["meeting", "email_draft", "task", "reminder", "note", "unknown"]
    title: str = ""
    when_text: str = ""
    duration_minutes: int = Field(default=30, ge=5, le=600)
    attendees: list[str] = Field(default_factory=list)
    wants_zoom: bool = False
    to: list[str] = Field(default_factory=list)
    subject: str = ""
    body: str = ""


class QuickCommandError(Exception):
    def __init__(self, message: str, status_code: int = 422):
        super().__init__(message)
        self.status_code = status_code


def parse_quick_command(
    db: OrmSession, user: User, text: str, router: ModelRouter | None = None
) -> ActionProposal:
    text = (text or "").strip()
    if not text:
        raise QuickCommandError("Empty command")
    if len(text) > MAX_COMMAND_CHARS:
        raise QuickCommandError(f"Command too long (max {MAX_COMMAND_CHARS} characters)")
    router = router or get_router()
    if not router.client.available():
        raise QuickCommandError("The local model is offline — start it with `localai start`", 503)

    try:
        intent = router.client.structured(
            model=router.model_for("extraction"),
            agent="productivity",
            purpose="extraction",
            system=SYSTEM,
            user=text,
            schema_model=QuickIntent,
            db=db,
            user_id=user.id,
        )
    except Exception as exc:  # transport, timeout, unparseable output
        raise QuickCommandError("The local model couldn't process that — try again", 503) from exc
    try:
        return _to_proposal(db, user, text, intent)
    except ValidationError as exc:  # e.g. a model-written title/body past the limits
        raise QuickCommandError(f"That produced an invalid request: {exc.errors()[0]['msg']}") from exc


def _verbatim(addresses: list[str], text: str) -> list[str]:
    """Keep only addresses the user actually typed. A prompt rule isn't enough:
    the model must not be able to invent a recipient or attendee."""
    lowered = text.lower()
    return [a.strip() for a in addresses if valid_email(a.strip()) and a.strip().lower() in lowered]


def _to_proposal(db: OrmSession, user: User, text: str, intent: QuickIntent) -> ActionProposal:
    reason = f"Quick command: {text}"

    if intent.intent == "meeting":
        when = normalize_when(intent.when_text, reference=utcnow(), tz_name=user.timezone)
        if when.normalized_at is None:
            raise QuickCommandError("I couldn't work out when — try e.g. 'tomorrow 3pm'")
        starts = when.normalized_at
        return propose(
            db,
            user,
            "create_meeting",
            {
                "provider": "zoom" if intent.wants_zoom else "google_meet",
                "title": intent.title or "Meeting",
                "starts_at": starts,
                "ends_at": starts + timedelta(minutes=intent.duration_minutes),
                "attendees": _verbatim(intent.attendees, text),
                "send_invites": False,  # only ever a deliberate human choice at approval
            },
            reason + ("" if not when.needs_review else " (time uncertain — please check)"),
            "quick-command",
        )
    if intent.intent == "email_draft":
        to = _verbatim(intent.to, text)
        if not to:
            raise QuickCommandError("No recipient email address found in the command")
        return propose(
            db,
            user,
            "create_email_draft",
            {"to": to, "subject": intent.subject or intent.title or "(no subject)", "body": intent.body},
            reason,
            "quick-command",
        )
    if intent.intent == "reminder":
        due = None
        if intent.when_text:
            when = normalize_when(intent.when_text, reference=utcnow(), tz_name=user.timezone)
            if when.normalized_at is None:
                raise QuickCommandError("I couldn't work out when — try e.g. 'tomorrow 3pm'")
            due = when.normalized_at
        return propose(
            db,
            user,
            "create_reminder",
            {"title": intent.title or text[:300], "due_at": due},
            reason,
            "quick-command",
        )
    if intent.intent == "task":
        return propose(
            db, user, "create_task", {"title": intent.title or text[:300]}, reason, "quick-command"
        )
    if intent.intent == "note":
        return propose(
            db,
            user,
            "create_note",
            {"title": intent.title or text[:80], "content": intent.body or text},
            reason,
            "quick-command",
        )
    raise QuickCommandError("I couldn't tell what to do with that — try rephrasing")
