"""Morning briefing: what deserves attention today (PRODUCT_SPEC.md §6).

Deterministic attention scoring + readiness; the LLM is only ever allowed to
polish wording, never to decide what matters.
"""

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session as OrmSession

from app.models import Deadline, Event, ReviewItem, Task, User
from app.models.enums import DeadlineStatus, EventKind, TaskStatus

# Attention weights: urgency dominates, but importance and risk matter.
W_URGENCY = 0.5
W_IMPORTANCE = 0.3
W_RISK = 0.2


def _urgency(deadline_at: datetime | None, now: datetime) -> float:
    if deadline_at is None:
        return 0.1
    hours_left = (deadline_at - now).total_seconds() / 3600
    if hours_left <= 0:
        return 1.0
    if hours_left <= 24:
        return 0.9
    if hours_left <= 72:
        return 0.7
    if hours_left <= 24 * 7:
        return 0.4
    return 0.15


def score_task(task: Task, deadline_at: datetime | None, now: datetime) -> tuple[float, str]:
    urgency = _urgency(deadline_at, now)
    importance = task.importance or 0.5
    unstarted = task.status == TaskStatus.pending
    risk = 0.9 if (unstarted and urgency >= 0.7) else 0.4 if unstarted else 0.1
    score = W_URGENCY * urgency + W_IMPORTANCE * importance + W_RISK * risk
    why = []
    if deadline_at:
        why.append(f"deadline {deadline_at.strftime('%a %d %b %H:%M')}")
    if unstarted and urgency >= 0.7:
        why.append("not started and due soon")
    why.append(f"importance {importance:.1f}")
    return score, "; ".join(why)


def build_briefing(db: OrmSession, user: User) -> dict:
    now = datetime.now(UTC)
    local_day_start = (now + timedelta(hours=0)).astimezone(
        _tz(user)
    )
    day_start = local_day_start.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)

    events = (
        db.execute(
            sa.select(Event)
            .where(Event.user_id == user.id, Event.starts_at >= day_start, Event.starts_at < day_end)
            .order_by(Event.starts_at)
        )
        .scalars()
        .all()
    )

    tasks = (
        db.execute(
            sa.select(Task).where(
                Task.user_id == user.id,
                Task.status.in_([TaskStatus.pending, TaskStatus.scheduled, TaskStatus.in_progress]),
            )
        )
        .scalars()
        .all()
    )
    deadlines = (
        db.execute(
            sa.select(Deadline).where(
                Deadline.user_id == user.id,
                Deadline.status == DeadlineStatus.confirmed,
                Deadline.normalized_at.isnot(None),
                Deadline.normalized_at >= now,
            )
        )
        .scalars()
        .all()
    )
    deadline_by_project = {d.project_id: d for d in deadlines}
    deadline_by_task = {d.task_id: d for d in deadlines if d.task_id}

    scored = []
    for task in tasks:
        deadline = deadline_by_task.get(task.id) or deadline_by_project.get(task.project_id)
        deadline_at = deadline.normalized_at if deadline else None
        score, why = score_task(task, deadline_at, now)
        scored.append({"task_id": str(task.id), "title": task.title, "score": round(score, 3),
                       "why": why, "status": task.status.value})
    scored.sort(key=lambda item: item["score"], reverse=True)

    # ---- risks ----
    risks = []
    for deadline in deadlines:
        hours_left = (deadline.normalized_at - now).total_seconds() / 3600
        related = [t for t in tasks if deadline_by_task.get(t.id) is deadline
                   or deadline_by_project.get(t.project_id) is deadline]
        open_minutes = sum(
            t.estimated_minutes or 60 for t in related
            if t.status in (TaskStatus.pending, TaskStatus.scheduled)
        )
        if hours_left <= 48 and related and all(
            t.status == TaskStatus.pending for t in related
        ):
            risks.append({
                "message": f"'{deadline.title}' is due in {hours_left:.0f}h and hasn't been started",
                "severity": "high",
                "evidence": {"deadline_id": str(deadline.id), "task_count": len(related)},
            })
        elif hours_left <= 72 and open_minutes > 0:
            free_before = _free_minutes_before(db, user, deadline.normalized_at)
            if free_before < open_minutes:
                risks.append({
                    "message": (
                        f"'{deadline.title}' needs ~{open_minutes // 60}h but only "
                        f"{free_before // 60}h of free time remains before it"
                    ),
                    "severity": "medium",
                    "evidence": {"deadline_id": str(deadline.id),
                                 "needed_minutes": open_minutes, "free_minutes": free_before},
                })
    conflicts = db.execute(
        sa.select(ReviewItem).where(
            ReviewItem.user_id == user.id,
            ReviewItem.status == "open",
            ReviewItem.kind.in_(["deadline_conflict", "injection"]),
        )
    ).scalars().all()
    for conflict in conflicts:
        risks.append({
            "message": conflict.question[:200],
            "severity": "high" if conflict.kind == "injection" else "medium",
            "evidence": {"review_id": str(conflict.id)},
        })

    # ---- suggestions (deterministic; each traceable to evidence) ----
    suggestions = []
    for item in scored[:3]:
        if item["score"] >= 0.6:
            suggestions.append({
                "action": f"Work on '{item['title']}' during your next free block",
                "why": item["why"],
            })
    overdue = [
        t for t in tasks if t.status == TaskStatus.scheduled
        and any(  # scheduled session already past and not completed
            e.task_id == t.id and e.kind == EventKind.focus and e.ends_at < now
            for e in db.execute(
                sa.select(Event).where(Event.user_id == user.id, Event.kind == EventKind.focus)
            ).scalars()
        )
    ]
    if overdue:
        suggestions.append({
            "action": f"{len(overdue)} planned session(s) slipped — recompute your plan on the Calendar page",
            "why": "missed sessions detected; the planner can rebuild around remaining free time",
        })

    # ---- upcoming windows ----
    upcoming = {}
    for days in (3, 7, 30):
        count = db.execute(
            sa.select(sa.func.count(Deadline.id)).where(
                Deadline.user_id == user.id,
                Deadline.status == DeadlineStatus.confirmed,
                Deadline.normalized_at.isnot(None),
                Deadline.normalized_at > now,
                Deadline.normalized_at <= now + timedelta(days=days),
            )
        ).scalar()
        upcoming[f"{days}_days"] = count

    return {
        "greeting": _greeting(now, user),
        "generated_at": now.isoformat(),
        "today": [
            {
                "id": str(e.id), "title": e.title, "kind": e.kind.value,
                "starts_at": e.starts_at.isoformat(), "ends_at": e.ends_at.isoformat(),
            }
            for e in events
        ],
        "top_priorities": scored[:5],
        "risks": risks,
        "suggestions": suggestions,
        "upcoming": upcoming,
        "readiness": [readiness_for(deadline, tasks, now) for deadline in deadlines[:5]],
    }


def readiness_for(deadline: Deadline, tasks: list[Task], now: datetime) -> dict:
    """Explained readiness score — components shown, never fake precision."""
    related = [t for t in tasks if t.status != TaskStatus.cancelled]
    done = [t for t in related if t.status == TaskStatus.done]
    coverage = len(done) / len(related) if related else 0.0
    hours_left = max((deadline.normalized_at - now).total_seconds() / 3600, 0)
    time_factor = min(hours_left / 72, 1.0)
    score = round(100 * (0.6 * coverage + 0.4 * time_factor))
    return {
        "deadline_id": str(deadline.id),
        "title": deadline.title,
        "score": score,
        "components": {
            "tasks_completed": f"{len(done)}/{len(related)}",
            "time_remaining_hours": round(hours_left, 1),
            "note": "heuristic: 60% completion + 40% remaining time",
        },
    }


def _tz(user: User):
    from zoneinfo import ZoneInfo

    return ZoneInfo(user.timezone or "Asia/Jakarta")


def _greeting(now: datetime, user: User) -> str:
    hour = now.astimezone(_tz(user)).hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def _free_minutes_before(db: OrmSession, user: User, until: datetime) -> int:
    """Rough free-time estimate inside work hours until a deadline."""
    now = datetime.now(UTC)
    work = user.work_hours or {}
    try:
        start_hour = int(str(work.get("start", "09:00")).split(":")[0])
        end_hour = int(str(work.get("end", "22:00")).split(":")[0])
    except ValueError:
        start_hour, end_hour = 9, 22
    busy = db.execute(
        sa.select(Event).where(
            Event.user_id == user.id,
            Event.starts_at >= now,
            Event.starts_at < until,
            Event.kind.in_([EventKind.hard, EventKind.deadline, EventKind.focus]),
        )
    ).scalars().all()
    busy_minutes = sum((e.ends_at - e.starts_at).total_seconds() / 60 for e in busy)
    days = max((until - now).total_seconds() / 86400, 0)
    capacity = days * (end_hour - start_hour) * 60
    return max(int(capacity - busy_minutes), 0)
