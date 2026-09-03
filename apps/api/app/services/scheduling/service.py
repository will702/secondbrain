"""Schedule service: DB rows ⇄ planner inputs, plan recomputation, rescheduling."""

import logging
from datetime import UTC, datetime
from datetime import time

import sqlalchemy as sa
from sqlalchemy.orm import Session as OrmSession

from app.models import AIDecision, Deadline, Event, Task, TaskDependency, User
from app.models.enums import DeadlineStatus, EventKind, TaskStatus
from app.services.scheduling.planner import (
    Planner,
    PlannerTask,
    apply_plan_to_calendar,
)

logger = logging.getLogger("secondbrain.schedule")


def _parse_hhmm(value: str, fallback: time) -> time:
    try:
        hour, minute = value.split(":")
        return time(int(hour), int(minute))
    except (ValueError, AttributeError):
        return fallback


def build_planner_tasks(db: OrmSession, user: User) -> list[PlannerTask]:
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
    deps_by_task: dict[str, list[str]] = {}
    if tasks:
        dependencies = (
            db.execute(
                sa.select(TaskDependency).where(
                    TaskDependency.task_id.in_([t.id for t in tasks])
                )
            )
            .scalars()
            .all()
        )
        for dep in dependencies:
            deps_by_task.setdefault(str(dep.task_id), []).append(str(dep.depends_on_task_id))

    planner_tasks: list[PlannerTask] = []
    for task in tasks:
        deadline_at: datetime | None = None
        if task.deadline_id:
            deadline = db.get(Deadline, task.deadline_id)
            deadline_at = deadline.normalized_at if deadline else None
        if deadline_at is None and task.project_id:
            # Nearest confirmed deadline in the same project grounds the task.
            project_deadline = db.execute(
                sa.select(Deadline)
                .where(
                    Deadline.user_id == user.id,
                    Deadline.project_id == task.project_id,
                    Deadline.status == DeadlineStatus.confirmed,
                    Deadline.normalized_at.isnot(None),
                )
                .order_by(Deadline.normalized_at.asc())
                .limit(1)
            ).scalar_one_or_none()
            deadline_at = project_deadline.normalized_at if project_deadline else None
        planner_tasks.append(
            PlannerTask(
                id=str(task.id),
                title=task.title,
                priority=task.priority,
                importance=task.importance or 0.5,
                estimated_minutes=task.estimated_minutes or 60,
                minimum_session_minutes=task.minimum_session_minutes or 30,
                preferred_time_of_day=task.preferred_time_of_day or "any",
                deadline=deadline_at,
                depends_on=deps_by_task.get(str(task.id), []),
            )
        )
    return planner_tasks


def recompute_plan(db: OrmSession, user: User, horizon_days: int = 14, apply: bool = True) -> dict:
    work = user.work_hours or {}
    planner = Planner(
        work_start=_parse_hhmm(work.get("start", "09:00"), time(9, 0)),
        work_end=_parse_hhmm(work.get("end", "22:00"), time(22, 0)),
        tz_name=user.timezone,
    )
    planner_tasks = build_planner_tasks(db, user)
    events = db.execute(
        sa.select(Event).where(Event.user_id == user.id)
    ).scalars().all()
    hard_events = [e for e in events if e.kind in (EventKind.hard, EventKind.deadline)]
    focus_events = [
        e for e in events if e.kind == EventKind.focus and e.starts_at > datetime.now(UTC)
    ]
    replace_ids = [str(e.task_id) for e in focus_events if e.task_id]
    plan = planner.plan(planner_tasks, hard_events, now=datetime.now(UTC), horizon_days=horizon_days)

    if not apply and user.autonomy_level < 2:
        # Assistant level (1) may not write calendar events — the computed plan
        # becomes one proposal per session; approving applies it.
        from app.services.proposals.service import propose

        created_proposals = 0
        for session in plan.sessions[:20]:
            propose(
                db, user, "create_event",
                {
                    "title": f"Focus: {session.title}",
                    "starts_at": session.start.isoformat(),
                    "ends_at": session.end.isoformat(),
                    "kind": "focus",
                },
                reason=f"Planner suggestion ({session.start.strftime('%a %H:%M')}): part of the computed plan for this task",
                proposed_by="planning",
                evidence={"task_id": session.task_id},
            )
            created_proposals += 1
        db.add(
            AIDecision(
                user_id=user.id,
                agent="planning",
                decision=f"Plan computed ({len(plan.sessions)} sessions) — proposed for approval",
                reason="autonomy level < 2: calendar writes require user approval",
                evidence={
                    "sessions": len(plan.sessions),
                    "proposals_created": created_proposals,
                    "infeasible": plan.infeasible,
                },
            )
        )
        db.commit()
        return {
            "sessions": 0,
            "tasks_planned": len({s.task_id for s in plan.sessions}),
            "proposals": created_proposals,
            "infeasible": plan.infeasible,
            "decisions": plan.decisions,
            "applied": False,
        }

    created = apply_plan_to_calendar(db, user, plan, replace_task_ids=replace_ids)

    scheduled_ids = {s.task_id for s in plan.sessions}
    for task_row in db.execute(
        sa.select(Task).where(
            Task.user_id == user.id,
            Task.status.in_([TaskStatus.pending, TaskStatus.scheduled]),
        )
    ).scalars():
        if str(task_row.id) in scheduled_ids:
            task_row.status = TaskStatus.scheduled
        elif task_row.status == TaskStatus.scheduled:
            task_row.status = TaskStatus.pending
    db.commit()
    return {
        "sessions": len(created),
        "tasks_planned": len(scheduled_ids),
        "infeasible": plan.infeasible,
        "decisions": plan.decisions,
        "applied": True,
    }


def reschedule_after_missed(db: OrmSession, user: User, event: Event) -> dict:
    """A focus session was missed/deleted: drop remaining future sessions of the
    same task (the planner rebuilds the whole task) and recompute. This is an
    explicit user action, so the rebuilt plan applies directly."""
    if event.kind != EventKind.focus or not event.task_id:
        return {"detail": "not a focus session"}
    future = db.execute(
        sa.select(Event).where(
            Event.user_id == user.id,
            Event.kind == EventKind.focus,
            Event.task_id == event.task_id,
            Event.starts_at > datetime.now(UTC),
        )
    ).scalars().all()
    for session in future:
        db.delete(session)
    db.commit()
    return recompute_plan(db, user, apply=True)
