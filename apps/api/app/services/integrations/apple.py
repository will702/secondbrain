"""Apple Reminders / Calendar / Mail drafts / Shortcuts via osascript.

Safety rules:
- argv only, never a shell; user text reaches AppleScript as `argv` items, never
  interpolated into script source, so quotes / `$()` / newlines are inert data.
- `--` precedes user args so a title like "-foo" is not parsed as an osascript option.
- Mail gets drafts only (saved, never sent).
- Off unless APPLE_ENABLED=true; macOS asks for Automation permission on first use.
"""

import subprocess
import sys
from datetime import datetime

from app.core.config import get_settings

TIMEOUT_S = 30  # a pending macOS permission dialog must not hang the worker


class AppleUnavailable(Exception):
    pass


_MKDATE = """
on mkdate(y, mo, d, h, mi)
  set x to current date
  set day of x to 1
  set year of x to (y as integer)
  set month of x to (mo as integer)
  set day of x to (d as integer)
  set hours of x to (h as integer)
  set minutes of x to (mi as integer)
  set seconds of x to 0
  return x
end mkdate
"""

REMINDER_SCRIPT = (
    """
on run argv
  set listName to item 1 of argv
  set theTitle to item 2 of argv
  set theNotes to item 3 of argv
  tell application "Reminders"
    set theList to first list whose name is listName
    set r to make new reminder at end of reminders of theList with properties {name:theTitle, body:theNotes}
    if (count of argv) > 3 then
      set due date of r to my mkdate(item 4 of argv, item 5 of argv, item 6 of argv, item 7 of argv, item 8 of argv)
    end if
    return id of r
  end tell
end run
"""
    + _MKDATE
)

CALENDAR_SCRIPT = (
    """
on run argv
  set calName to item 1 of argv
  set theTitle to item 2 of argv
  set theNotes to item 3 of argv
  set s to my mkdate(item 4 of argv, item 5 of argv, item 6 of argv, item 7 of argv, item 8 of argv)
  set e to my mkdate(item 9 of argv, item 10 of argv, item 11 of argv, item 12 of argv, item 13 of argv)
  tell application "Calendar"
    set theCal to first calendar whose name is calName
    set ev to make new event at end of events of theCal with properties {summary:theTitle, start date:s, end date:e, description:theNotes}
    return uid of ev
  end tell
end run
"""
    + _MKDATE
)

MAIL_DRAFT_SCRIPT = """
on run argv
  set theSubject to item 1 of argv
  set theBody to item 2 of argv
  tell application "Mail"
    set msg to make new outgoing message with properties {subject:theSubject, content:theBody, visible:false}
    repeat with i from 3 to (count of argv)
      tell msg to make new to recipient at end of to recipients with properties {address:(item i of argv)}
    end repeat
    save msg
  end tell
  return "saved"
end run
"""


def _require_enabled() -> None:
    if sys.platform != "darwin":
        raise AppleUnavailable("Apple integrations only work on macOS")
    if not get_settings().apple_enabled:
        raise AppleUnavailable("Apple integrations are off — set APPLE_ENABLED=true")


def _run(argv: list[str]) -> str:
    try:
        proc = subprocess.run(  # noqa: S603 — argv list, no shell
            argv, capture_output=True, text=True, timeout=TIMEOUT_S, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AppleUnavailable(f"{argv[0]} failed: {exc}") from exc
    if proc.returncode != 0:
        raise AppleUnavailable(proc.stderr.strip()[:300] or f"{argv[0]} exited {proc.returncode}")
    return proc.stdout.strip()


def _osascript(script: str, args: list[str]) -> str:
    return _run(["osascript", "-e", script, "--", *args])


def _date_parts(dt: datetime) -> list[str]:
    local = dt.astimezone()  # AppleScript works in the Mac's local time
    return [str(local.year), str(local.month), str(local.day), str(local.hour), str(local.minute)]


def create_reminder(
    *, title: str, due_at: datetime | None = None, list_name: str = "Reminders", notes: str = ""
) -> dict:
    _require_enabled()
    args = [list_name, title, notes]
    if due_at is not None:
        args += _date_parts(due_at)
    return {"reminder_id": _osascript(REMINDER_SCRIPT, args)}


def create_calendar_event(
    *, title: str, starts_at: datetime, ends_at: datetime, calendar: str | None = None, notes: str = ""
) -> dict:
    _require_enabled()
    calendar = calendar or get_settings().apple_calendar_name
    args = [calendar, title, notes, *_date_parts(starts_at), *_date_parts(ends_at)]
    return {"event_uid": _osascript(CALENDAR_SCRIPT, args)}


def create_mail_draft(*, to: list[str], subject: str, body: str) -> dict:
    """Saves a draft in Mail.app. Never sends."""
    _require_enabled()
    _osascript(MAIL_DRAFT_SCRIPT, [subject, body, *to])
    return {"saved": True}


def run_shortcut(name: str) -> dict:
    """Runs an existing Shortcut by exact name (typos can't run anything else)."""
    _require_enabled()
    if not name or name.startswith("-"):
        raise AppleUnavailable("invalid shortcut name")
    available = _run(["shortcuts", "list"]).splitlines()
    if name not in available:
        raise AppleUnavailable(f"no Shortcut named {name!r}")
    return {"output": _run(["shortcuts", "run", name])[:500]}
