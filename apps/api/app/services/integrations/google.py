"""Google Calendar (Meet links) + Gmail drafts, on top of the existing OAuth
tokens in services/calendar. Drafts only: there is deliberately no send call."""

import base64
import re
from email.message import EmailMessage

import httpx
from sqlalchemy.orm import Session as OrmSession

from app.models import User
from app.services import calendar as cal

CAL_EVENTS = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
GMAIL_DRAFTS = "https://gmail.googleapis.com/gmail/v1/users/me/drafts"
EMAIL_RE = re.compile(r"^[^@\s,<>;]+@[^@\s,<>;]+\.[^@\s,<>;]+$")


class GoogleUnavailable(Exception):
    """Not connected / missing scope / API refused."""


def valid_email(addr: str) -> bool:
    return bool(EMAIL_RE.match(addr))


def _request(db: OrmSession, user: User, method: str, url: str, **kwargs) -> dict:
    tokens = cal._google_tokens(db, user)
    if tokens is None:
        raise GoogleUnavailable("Google is not connected")
    for attempt in (1, 2):
        response = httpx.request(
            method,
            url,
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
            timeout=20,
            **kwargs,
        )
        if response.status_code == 401 and attempt == 1 and cal._google_refresh(db, user, tokens):
            continue  # tokens dict was refreshed in place
        break
    if response.status_code in (401, 403):
        raise GoogleUnavailable(
            "Google refused the request — reconnect Google to grant the new permissions"
        )
    if response.status_code >= 400:
        raise GoogleUnavailable(f"Google API error {response.status_code}")
    return response.json()


def create_meet_event(
    db: OrmSession,
    user: User,
    *,
    title: str,
    starts_at,
    ends_at,
    attendees: list[str],
    description: str,
    send_invites: bool,
    request_id: str,
) -> dict:
    """Create a calendar event with a Meet link. Attendees are only emailed when
    send_invites is true (the user ticked it before approving)."""
    body = {
        "summary": title,
        "description": description,
        "start": {"dateTime": starts_at.isoformat(), "timeZone": user.timezone},
        "end": {"dateTime": ends_at.isoformat(), "timeZone": user.timezone},
        "attendees": [{"email": a} for a in attendees],
        "conferenceData": {
            "createRequest": {
                "requestId": request_id,  # stable per proposal => no duplicate conferences
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        },
    }
    data = _request(
        db,
        user,
        "POST",
        CAL_EVENTS,
        params={
            "conferenceDataVersion": 1,
            "sendUpdates": "all" if (send_invites and attendees) else "none",
        },
        json=body,
    )
    meet_url = data.get("hangoutLink")
    if not meet_url:
        for ep in (data.get("conferenceData") or {}).get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                meet_url = ep.get("uri")
    return {"google_event_id": data.get("id"), "meet_url": meet_url, "html_link": data.get("htmlLink")}


def create_draft(db: OrmSession, user: User, *, to: list[str], subject: str, body: str) -> dict:
    """Save a Gmail draft. Never sends."""
    msg = EmailMessage()  # default policy rejects header injection (newlines)
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    data = _request(db, user, "POST", GMAIL_DRAFTS, json={"message": {"raw": raw}})
    return {"draft_id": data.get("id")}
