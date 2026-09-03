import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session as OrmSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import AuditLog, Event, User
from app.services.calendar import (
    create_event,
    detect_overlap,
    export_ics,
    get_events,
    google_authorization_url,
    google_exchange_and_store,
    google_status,
    google_sync,
    import_ics,
)
from app.services.scheduling.service import recompute_plan, reschedule_after_missed

router = APIRouter(tags=["calendar"])


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    title: str
    starts_at: datetime
    ends_at: datetime
    all_day: bool
    timezone: str
    location: str | None
    provider: str
    task_id: uuid.UUID | None
    project_id: uuid.UUID | None
    editable: bool


class EventCreate(BaseModel):
    title: str
    starts_at: datetime
    ends_at: datetime
    kind: str = "hard"
    location: str | None = None
    description: str | None = None


@router.get("/calendar", response_model=list[EventOut])
def list_calendar(
    days: int = 14,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    now = datetime.now(UTC)
    return get_events(db, user, now - timedelta(days=1), now + timedelta(days=days))


@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def create_calendar_event(
    body: EventCreate,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    if body.ends_at <= body.starts_at:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "ends_at must be after starts_at")
    overlap = detect_overlap(db, user, body.starts_at, body.ends_at)
    if overlap is not None and body.kind == "hard":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Overlaps existing hard event '{overlap.title}' ({overlap.starts_at}–{overlap.ends_at})",
        )
    event = create_event(
        db,
        user,
        kind=body.kind,
        title=body.title,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        location=body.location,
        description=body.description,
        provider="local",
    )
    db.add(
        AuditLog(
            user_id=user.id,
            actor="user",
            action="event.create",
            object_type="event",
            object_id=str(event.id),
        )
    )
    db.commit()
    return event


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    event = db.get(Event, event_id)
    if event is None or event.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    if not event.editable:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This event is managed by its source provider (Google/ics) and cannot be deleted here",
        )
    was_focus = event.kind == "focus"
    db.delete(event)
    db.add(
        AuditLog(
            user_id=user.id,
            actor="user",
            action="event.delete",
            object_type="event",
            object_id=str(event_id),
        )
    )
    db.commit()
    if was_focus:
        reschedule_after_missed(db, user, event)
    return None


@router.post("/calendar/import-ics")
async def import_ics_route(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    text = (await file.read()).decode("utf-8", errors="replace")
    result = import_ics(db, user, text)
    db.add(AuditLog(user_id=user.id, actor="user", action="calendar.import_ics", detail=result))
    db.commit()
    return result


@router.get("/calendar/export.ics", response_class=PlainTextResponse)
def export_ics_route(
    days: int = 30,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    now = datetime.now(UTC)
    return export_ics(db, user, now, now + timedelta(days=days))


@router.get("/calendar/google/status")
def google_status_route(user: User = Depends(get_current_user), db: OrmSession = Depends(get_db)):
    return google_status(db, user)


@router.get("/auth/google/connect")
def google_connect(user: User = Depends(get_current_user)):
    from app.core.config import get_settings

    settings = get_settings()
    if not (settings.google_client_id and settings.google_client_secret):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env.",
        )
    url = google_authorization_url(state=str(user.id))
    if url is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Missing GOOGLE_REDIRECT_URI")
    return {"authorization_url": url}


@router.get("/auth/google/callback")
def google_callback(
    code: str,
    state: str,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    """OAuth redirect target: the user's browser lands here with our session
    cookie; exchange the code and store encrypted tokens for this user."""
    if state != str(user.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "state mismatch")
    google_exchange_and_store(db, user, code)
    db.add(
        AuditLog(
            user_id=user.id,
            actor="user",
            action="integration.connect",
            object_type="integration",
            object_id="google_calendar",
        )
    )
    db.commit()
    return {"detail": "Google Calendar connected. You can now sync."}


@router.post("/calendar/google/sync")
def google_sync_route(user: User = Depends(get_current_user), db: OrmSession = Depends(get_db)):
    status_report = google_status(db, user)
    if not status_report["connected"]:
        raise HTTPException(status.HTTP_409_CONFLICT, status_report["detail"])
    return google_sync(db, user)


@router.post("/schedule/recompute")
def schedule_recompute(user: User = Depends(get_current_user), db: OrmSession = Depends(get_db)):
    # Explicit request, but calendar writes still respect autonomy: below level 2
    # the plan comes back as proposals to approve (permission architecture, SECURITY.md §3).
    return recompute_plan(db, user, apply=user.autonomy_level >= 2)


@router.post("/schedule/missed/{event_id}")
def schedule_missed(
    event_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    event = db.get(Event, event_id)
    if event is None or event.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    db.add(
        AuditLog(
            user_id=user.id,
            actor="user",
            action="schedule.session_missed",
            object_type="event",
            object_id=str(event_id),
        )
    )
    return reschedule_after_missed(db, user, event)
