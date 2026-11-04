"""Read-only system visibility: how loaded is the user, and what has the
system done lately. Nothing here mutates state."""

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session as OrmSession

from app.models import ActionExecution, AuditLog, Event, User
from app.models.enums import EventKind

HEAVY_PCT = 70
LIGHT_PCT = 30


def load_level(booked_pct: int) -> str:
    if booked_pct >= HEAVY_PCT:
        return "heavy"
    if booked_pct <= LIGHT_PCT:
        return "light"
    return "normal"


def _work_hours(user: User) -> int:
    work = user.work_hours or {}
    try:
        start = int(str(work.get("start", "09:00")).split(":")[0])
        end = int(str(work.get("end", "22:00")).split(":")[0])
    except ValueError:
        start, end = 9, 22
    return max(end - start, 1)


def _window(db: OrmSession, user: User, days: float) -> dict:
    now = datetime.now(UTC)
    until = now + timedelta(days=days)
    events = (
        db.execute(
            sa.select(Event).where(
                Event.user_id == user.id,
                Event.starts_at >= now,
                Event.starts_at < until,
                Event.all_day.is_(False),
                Event.kind.in_([EventKind.hard, EventKind.deadline, EventKind.focus]),
            )
        )
        .scalars()
        .all()
    )
    busy = sum((e.ends_at - e.starts_at).total_seconds() / 60 for e in events)
    capacity = days * _work_hours(user) * 60
    pct = min(int(round(100 * busy / capacity)), 100) if capacity else 0
    return {
        "booked_pct": pct,
        "booked_minutes": int(busy),
        "free_minutes": max(int(capacity - busy), 0),
        "level": load_level(pct),
    }


def booked_load(db: OrmSession, user: User) -> dict:
    """Used by the PMAX watcher to stay quiet on heavy days."""
    return {"today": _window(db, user, 1), "week": _window(db, user, 7)}


def activity_feed(
    db: OrmSession, user: User, limit: int = 30, before: datetime | None = None
) -> list[dict]:
    """Merged audit + execution feed, newest first: 'what did the system do?'"""
    audit_q = sa.select(AuditLog).where(AuditLog.user_id == user.id)
    exec_q = sa.select(ActionExecution).where(ActionExecution.user_id == user.id)
    if before is not None:
        audit_q = audit_q.where(AuditLog.created_at < before)
        exec_q = exec_q.where(ActionExecution.created_at < before)
    audits = db.execute(audit_q.order_by(AuditLog.created_at.desc()).limit(limit)).scalars().all()
    execs = (
        db.execute(exec_q.order_by(ActionExecution.created_at.desc()).limit(limit)).scalars().all()
    )
    items = [
        {
            "kind": "audit",
            "at": a.created_at,
            "actor": a.actor,
            "action": a.action,
            "object": {"type": a.object_type, "id": a.object_id},
            "detail": a.detail,
        }
        for a in audits
    ] + [
        {
            "kind": "execution",
            "at": x.created_at,
            "actor": "system",
            "action": f"proposal.execute.{x.status}",
            "object": {"type": "proposal", "id": str(x.proposal_id)},
            "detail": {"result": x.result, "error": x.error},
        }
        for x in execs
    ]
    items.sort(key=lambda i: i["at"], reverse=True)
    return items[:limit]
