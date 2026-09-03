"""Calendar service: local events, .ics import/export, Google adapter.

Providers implement a narrow interface (ARCHITECTURE.md §6). Google stays
dormant until credentials exist — everything else keeps working.
"""

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session as OrmSession

from app.models import Event, Integration, User
from app.models.enums import EventKind


def get_events(db: OrmSession, user: User, start: datetime, end: datetime) -> list[Event]:
    return (
        db.execute(
            sa.select(Event)
            .where(Event.user_id == user.id, Event.starts_at >= start, Event.starts_at <= end)
            .order_by(Event.starts_at)
        )
        .scalars()
        .all()
    )


def create_event(db: OrmSession, user: User, **kwargs) -> Event:
    event = Event(user_id=user.id, timezone=user.timezone, **kwargs)
    db.add(event)
    db.flush()
    return event


def detect_overlap(db: OrmSession, user: User, starts_at: datetime, ends_at: datetime) -> Event | None:
    return (
        db.execute(
            sa.select(Event)
            .where(
                Event.user_id == user.id,
                Event.kind.in_([EventKind.hard, EventKind.deadline]),
                Event.starts_at < ends_at,
                Event.ends_at > starts_at,
            )
            .limit(1)
        )
        .scalar_one_or_none()
    )


# ---------------------------------------------------------------- ics import

def import_ics(db: OrmSession, user: User, ics_text: str) -> dict:
    from icalendar import Calendar

    calendar = Calendar.from_ical(ics_text)
    imported, skipped = 0, 0
    for component in calendar.walk("VEVENT"):
        try:
            summary = str(component.get("SUMMARY", "Imported event"))
            dt_start = component.get("DTSTART").dt
            dt_end = component.get("DTEND")
            dt_end = dt_end.dt if dt_end is not None else dt_start + timedelta(hours=1)
            if isinstance(dt_start, datetime):
                start = dt_start if dt_start.tzinfo else dt_start.replace(tzinfo=UTC)
                end = dt_end if getattr(dt_end, "tzinfo", None) else dt_end.replace(tzinfo=UTC)
            else:  # all-day date
                start = datetime(dt_start.year, dt_start.month, dt_start.day, tzinfo=UTC)
                end = datetime(dt_end.year, dt_end.month, dt_end.day, 23, 59, tzinfo=UTC)

            uid = str(component.get("UID", "")) or None
            if uid:
                existing = db.execute(
                    sa.select(Event).where(
                        Event.user_id == user.id,
                        Event.provider == "ics",
                        Event.provider_event_id == uid,
                    )
                ).scalar_one_or_none()
                if existing is not None:
                    skipped += 1
                    continue

            db.add(
                Event(
                    user_id=user.id,
                    kind=EventKind.hard,
                    title=summary,
                    starts_at=start,
                    ends_at=end,
                    all_day=not isinstance(dt_start, datetime),
                    timezone=user.timezone,
                    location=str(component.get("LOCATION")) if component.get("LOCATION") else None,
                    provider="ics",
                    provider_event_id=uid,
                    editable=False,
                    provenance={"imported_from": "ics"},
                )
            )
            imported += 1
        except Exception:
            skipped += 1
            continue
    db.commit()
    return {"imported": imported, "skipped": skipped}


def export_ics(db: OrmSession, user: User, start: datetime, end: datetime) -> str:
    from icalendar import Calendar
    from icalendar import Event as IcsEvent

    calendar = Calendar()
    calendar.add("PRODID", "-//Second Brain OS//EN")
    calendar.add("VERSION", "2.0")
    for event in get_events(db, user, start, end):
        component = IcsEvent()
        component.add("UID", str(event.id))
        component.add("SUMMARY", event.title)
        component.add("DTSTART", event.starts_at)
        component.add("DTEND", event.ends_at)
        if event.location:
            component.add("LOCATION", event.location)
        calendar.add_component(component)
    return calendar.to_ical().decode()


# ---------------------------------------------------------------- google

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]


def google_status(db: OrmSession, user: User) -> dict:
    from app.core.config import get_settings

    settings = get_settings()
    if not (settings.google_client_id and settings.google_client_secret):
        return {"configured": False, "connected": False,
                "detail": "Set GOOGLE_CLIENT_ID/SECRET in .env to enable Google Calendar"}
    integration = db.execute(
        sa.select(Integration).where(
            Integration.user_id == user.id, Integration.provider == "google_calendar"
        )
    ).scalar_one_or_none()
    if integration is None or integration.status != "connected":
        return {"configured": True, "connected": False,
                "detail": "Not connected — visit /auth/google/connect"}
    return {"configured": True, "connected": True,
            "detail": f"Last synced: {integration.last_synced_at}"}


def google_authorization_url(state: str) -> str | None:
    from app.core.config import get_settings

    settings = get_settings()
    if not (settings.google_client_id and settings.google_redirect_uri):
        return None
    from urllib.parse import urlencode

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


def google_exchange_and_store(db: OrmSession, user: User, code: str) -> Integration:
    import httpx

    from app.core.config import get_settings
    from app.core.crypto import encrypt_json

    settings = get_settings()
    response = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    response.raise_for_status()
    tokens = response.json()

    integration = db.execute(
        sa.select(Integration).where(
            Integration.user_id == user.id, Integration.provider == "google_calendar"
        )
    ).scalar_one_or_none()
    if integration is None:
        integration = Integration(
            user_id=user.id, provider="google_calendar", scopes=GOOGLE_SCOPES
        )
        db.add(integration)
    integration.encrypted_credentials = encrypt_json(tokens)
    integration.status = "connected"
    db.commit()
    return integration


def _google_tokens(db: OrmSession, user: User) -> dict | None:
    from app.core.crypto import decrypt_json

    integration = db.execute(
        sa.select(Integration).where(
            Integration.user_id == user.id, Integration.provider == "google_calendar"
        )
    ).scalar_one_or_none()
    if integration is None or not integration.encrypted_credentials:
        return None
    return decrypt_json(integration.encrypted_credentials)


def google_sync(db: OrmSession, user: User, window_days: int = 30) -> dict:
    """Mirror Google events into local rows (read direction). Upserts by
    provider_event_id; never deletes local-only events."""
    import httpx

    tokens = _google_tokens(db, user)
    if tokens is None:
        return {"synced": 0, "detail": "not connected"}

    from datetime import datetime as _dt

    now = _dt.now(UTC)
    params = {
        "timeMin": now.isoformat(),
        "timeMax": (now + timedelta(days=window_days)).isoformat(),
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": 250,
    }
    response = httpx.get(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        params=params,
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
        timeout=20,
    )
    if response.status_code == 401 and tokens.get("refresh_token"):
        # Refresh once, then retry.
        refreshed = _google_refresh(db, user, tokens)
        if refreshed:
            return google_sync(db, user, window_days)
    response.raise_for_status()
    items = response.json().get("items", [])

    synced = 0
    for item in items:
        start_raw = item.get("start", {})
        end_raw = item.get("end", {})
        dt_start = start_raw.get("dateTime")
        dt_end = end_raw.get("dateTime")
        if not dt_start:
            continue  # all-day events need date handling — Phase 2 polish
        start = datetime.fromisoformat(dt_start.replace("Z", "+00:00"))
        end = (
            datetime.fromisoformat(dt_end.replace("Z", "+00:00"))
            if dt_end
            else start + timedelta(hours=1)
        )
        existing = db.execute(
            sa.select(Event).where(
                Event.user_id == user.id,
                Event.provider == "google",
                Event.provider_event_id == item["id"],
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.starts_at, existing.ends_at, existing.title = start, end, item.get("summary", "")
        else:
            db.add(
                Event(
                    user_id=user.id,
                    kind=EventKind.hard,
                    title=item.get("summary", "Google event"),
                    starts_at=start,
                    ends_at=end,
                    timezone=user.timezone,
                    provider="google",
                    provider_event_id=item["id"],
                    editable=False,
                    provenance={"imported_from": "google"},
                )
            )
        synced += 1
    integration = db.execute(
        sa.select(Integration).where(
            Integration.user_id == user.id, Integration.provider == "google_calendar"
        )
    ).scalar_one()
    from datetime import datetime as _dt2

    integration.last_synced_at = _dt2.now(UTC)
    db.commit()
    return {"synced": synced, "detail": "ok"}


def _google_refresh(db: OrmSession, user: User, tokens: dict) -> bool:
    import httpx

    from app.core.config import get_settings
    from app.core.crypto import encrypt_json

    settings = get_settings()
    if not tokens.get("refresh_token"):
        return False
    response = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "refresh_token": tokens["refresh_token"],
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    if response.status_code != 200:
        return False
    tokens.update(response.json())
    integration = db.execute(
        sa.select(Integration).where(
            Integration.user_id == user.id, Integration.provider == "google_calendar"
        )
    ).scalar_one()
    integration.encrypted_credentials = encrypt_json(tokens)
    db.commit()
    return True
