"""Zoom meetings via Server-to-Server OAuth (account credentials grant).

Creates the meeting only. Zoom does not email attendees from this call, so
Zoom proposals never claim to send invites."""

import time
from datetime import UTC, datetime

import httpx

from app.core.config import get_settings

TOKEN_URL = "https://zoom.us/oauth/token"
MEETINGS_URL = "https://api.zoom.us/v2/users/me/meetings"

_token: dict = {"value": None, "expires": 0.0}


class ZoomUnavailable(Exception):
    pass


def _access_token() -> str:
    s = get_settings()
    if not (s.zoom_account_id and s.zoom_client_id and s.zoom_client_secret):
        raise ZoomUnavailable("Zoom is not configured (ZOOM_ACCOUNT_ID / CLIENT_ID / CLIENT_SECRET)")
    if _token["value"] and time.time() < _token["expires"] - 60:
        return _token["value"]
    response = httpx.post(
        TOKEN_URL,
        params={"grant_type": "account_credentials", "account_id": s.zoom_account_id},
        auth=(s.zoom_client_id, s.zoom_client_secret),
        timeout=15,
    )
    if response.status_code != 200:
        raise ZoomUnavailable(f"Zoom auth failed ({response.status_code})")
    data = response.json()
    _token["value"] = data["access_token"]
    _token["expires"] = time.time() + int(data.get("expires_in", 3000))
    return _token["value"]


def create_meeting(
    *, topic: str, starts_at: datetime, duration_minutes: int, timezone: str, agenda: str = ""
) -> dict:
    response = httpx.post(
        MEETINGS_URL,
        headers={"Authorization": f"Bearer {_access_token()}"},
        json={
            "topic": topic,
            "type": 2,  # scheduled
            "start_time": starts_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "duration": duration_minutes,
            "timezone": timezone,
            "agenda": agenda,
        },
        timeout=20,
    )
    if response.status_code >= 400:
        raise ZoomUnavailable(f"Zoom API error {response.status_code}")
    data = response.json()
    return {"zoom_meeting_id": str(data.get("id")), "join_url": data.get("join_url")}
