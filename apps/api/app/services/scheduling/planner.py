"""Availability + deterministic constraint scheduler (ARCHITECTURE.md, ADR-005).

The LLM estimates task metadata; THIS code places sessions. Constraints:
- hard/deadline events are immovable; plans only fill free time
- work hours respected; per-day focus cap; buffer between sessions
- min session length; dependency ordering; deadline feasibility checked

Every placement produces an explainable decision. Sessions become soft/focus
events — hard events are never created or moved by the planner.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from datetime import time as dt_time
from zoneinfo import ZoneInfo

from app.models import AIDecision, Event
from app.models.enums import EventKind

logger = logging.getLogger("secondbrain.planner")

MAX_SESSION_MINUTES = 120
BUFFER_MINUTES = 15
DEFAULT_FOCUS_CAP = 6 * 60
DEFAULT_ESTIMATE_MINUTES = 60

PREFERRED_WINDOWS = {
    "morning": (dt_time(6, 0), dt_time(12, 0)),
    "afternoon": (dt_time(12, 0), dt_time(18, 0)),
    "evening": (dt_time(18, 0), dt_time(23, 59)),
}


@dataclass
class Interval:
    start: datetime
    end: datetime

    def overlaps(self, other: "Interval") -> bool:
        return self.start < other.end and other.start < self.end

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class PlannerTask:
    id: str
    title: str
    priority: int = 3
    importance: float = 0.5
    estimated_minutes: int = DEFAULT_ESTIMATE_MINUTES
    minimum_session_minutes: int = 30
    preferred_time_of_day: str = "any"
    deadline: datetime | None = None
    depends_on: list[str] = field(default_factory=list)


@dataclass
class SessionPlan:
    task_id: str
    title: str
    start: datetime
    end: datetime


@dataclass
class PlanResult:
    sessions: list[SessionPlan] = field(default_factory=list)
    decisions: list[dict] = field(default_factory=list)
    infeasible: list[str] = field(default_factory=list)


def merge_intervals(intervals: list[Interval]) -> list[Interval]:
    merged: list[Interval] = []
    for interval in sorted(intervals, key=lambda i: i.start):
        if merged and interval.start <= merged[-1].end:
            merged[-1] = Interval(merged[-1].start, max(merged[-1].end, interval.end))
        else:
            merged.append(interval)
    return merged


class Planner:
    def __init__(
        self,
        work_start: dt_time,
        work_end: dt_time,
        tz_name: str,
        focus_cap: int = DEFAULT_FOCUS_CAP,
    ):
        self.work_start = work_start
        self.work_end = work_end
        self.tz = ZoneInfo(tz_name)
        self.focus_cap = focus_cap

    def _day_windows(self, day, preferred: str) -> list[Interval]:
        """Usable windows for a day: work hours ∩ preferred window."""
        windows = [
            Interval(
                datetime.combine(day, self.work_start, tzinfo=self.tz),
                datetime.combine(day, self.work_end, tzinfo=self.tz),
            )
        ]
        pref = PREFERRED_WINDOWS.get(preferred)
        if pref:
            pref_interval = Interval(
                datetime.combine(day, pref[0], tzinfo=self.tz),
                datetime.combine(day, pref[1], tzinfo=self.tz),
            )
            windows = [
                Interval(max(w.start, pref_interval.start), min(w.end, pref_interval.end))
                for w in windows
                if w.overlaps(pref_interval)
            ]
        return [w for w in windows if w.minutes > 0]

    def _free_in(self, window: Interval, busy: list[Interval]) -> list[Interval]:
        free: list[Interval] = []
        cursor = window.start
        for block in merge_intervals([b for b in busy if b.overlaps(window)]):
            if block.start > cursor:
                free.append(Interval(cursor, block.start))
            cursor = max(cursor, block.end)
        if cursor < window.end:
            free.append(Interval(cursor, window.end))
        return free

    def plan(
        self,
        tasks: list[PlannerTask],
        events: list[Event],
        now: datetime,
        horizon_days: int = 14,
    ) -> PlanResult:
        result = PlanResult()
        busy: list[Interval] = [
            Interval(e.starts_at, e.ends_at)
            for e in events
            if e.kind in (EventKind.hard, EventKind.deadline)
        ]
        focus_by_day: dict = {}
        session_end_by_task: dict[str, datetime] = {}

        def sort_key(task: PlannerTask):
            return (
                task.priority,
                task.deadline.timestamp() if task.deadline else float("inf"),
                -task.importance,
            )

        # Ready-queue scheduling: a task is planned only after everything it
        # depends on; among ready tasks, priority/deadline/importance order wins.
        input_ids = {t.id for t in tasks}
        remaining_tasks = list(tasks)
        while remaining_tasks:
            planned_ids = input_ids - {t.id for t in remaining_tasks}
            ready = [
                t
                for t in remaining_tasks
                if all(d not in input_ids or d in planned_ids for d in t.depends_on)
            ]
            if not ready:  # cycle — fall back to ignoring the cyclic edges
                ready = list(remaining_tasks)
            task = min(ready, key=sort_key)
            remaining_tasks.remove(task)
            remaining = task.estimated_minutes
            earliest = now
            for dep in task.depends_on:
                earliest = max(earliest, session_end_by_task.get(dep, now))
            start_day = earliest.astimezone(self.tz).date()
            deadline_day = task.deadline.astimezone(self.tz).date() if task.deadline else None
            sessions_for_task = 0

            day = start_day
            while remaining > 0:
                if deadline_day and day > deadline_day:
                    result.infeasible.append(task.id)
                    result.decisions.append(
                        {
                            "decision": f"Could not fully schedule '{task.title}'",
                            "reason": (
                                f"{remaining} min do not fit before its deadline "
                                f"{deadline_day.isoformat()} within work hours"
                            ),
                            "evidence": {"task_id": task.id, "minutes_left": remaining},
                        }
                    )
                    break
                if (day - start_day).days >= horizon_days:
                    result.infeasible.append(task.id)
                    result.decisions.append(
                        {
                            "decision": f"Scheduled part of '{task.title}' only",
                            "reason": f"Horizon of {horizon_days} days exhausted with {remaining} min left",
                            "evidence": {"task_id": task.id, "minutes_left": remaining},
                        }
                    )
                    break

                day_focus = focus_by_day.get(day, 0)
                for window in self._day_windows(day, task.preferred_time_of_day):
                    if remaining <= 0 or day_focus >= self.focus_cap:
                        break
                    usable = min(self.focus_cap - day_focus, MAX_SESSION_MINUTES, remaining)
                    if usable < min(task.minimum_session_minutes, remaining):
                        continue
                    for free in self._free_in(window, busy):
                        # Clip to `earliest` instead of skipping: a free block
                        # that started before now still has usable time left.
                        start = max(free.start, earliest)
                        length = min(usable, int((free.end - start).total_seconds() // 60))
                        if length < min(task.minimum_session_minutes, remaining):
                            continue
                        session = SessionPlan(
                            task_id=task.id,
                            title=task.title,
                            start=start,
                            end=start + timedelta(minutes=length),
                        )
                        result.sessions.append(session)
                        sessions_for_task += 1
                        day_focus += length
                        focus_by_day[day] = day_focus
                        remaining -= length
                        # Session + buffer become busy.
                        busy.append(
                            Interval(
                                session.start,
                                session.end + timedelta(minutes=BUFFER_MINUTES),
                            )
                        )
                        break
                day = day + timedelta(days=1)

            if sessions_for_task and remaining <= 0:
                result.decisions.append(
                    {
                        "decision": f"Scheduled '{task.title}' in {sessions_for_task} session(s)",
                        "reason": self._reason(task),
                        "evidence": {
                            "task_id": task.id,
                            "priority": task.priority,
                            "estimated_minutes": task.estimated_minutes,
                        },
                    }
                )
            session_end_by_task[task.id] = max(
                (s.end for s in result.sessions if s.task_id == task.id),
                default=now,
            )
        return result

    @staticmethod
    def _reason(task: PlannerTask) -> str:
        bits = [f"priority {task.priority}"]
        if task.deadline:
            bits.append(f"deadline {task.deadline.astimezone(ZoneInfo('UTC')).date().isoformat()}")
        if task.preferred_time_of_day in PREFERRED_WINDOWS:
            bits.append(f"prefers {task.preferred_time_of_day}")
        return "; ".join(bits)


def apply_plan_to_calendar(
    db, user, plan: PlanResult, replace_task_ids: list[str] | None = None
) -> list[Event]:
    """Write planned sessions as focus events, replacing prior focus events of
    the same tasks. Hard events are never touched."""
    from sqlalchemy import select

    task_ids = {s.task_id for s in plan.sessions} | set(replace_task_ids or [])
    if task_ids:
        prior = (
            db.execute(
                select(Event).where(
                    Event.user_id == user.id,
                    Event.kind == EventKind.focus,
                    Event.task_id.in_(task_ids),
                )
            )
            .scalars()
            .all()
        )
        for event in prior:
            db.delete(event)

    created = []
    for session in plan.sessions:
        event = Event(
            user_id=user.id,
            kind=EventKind.focus,
            title=f"Focus: {session.title}",
            starts_at=session.start,
            ends_at=session.end,
            timezone=user.timezone,
            task_id=session.task_id,
            editable=True,
            provenance={"planner": "deterministic:v1"},
        )
        db.add(event)
        created.append(event)
    for decision in plan.decisions:
        db.add(
            AIDecision(
                user_id=user.id,
                agent="planning",
                decision=decision["decision"],
                reason=decision["reason"],
                evidence=decision["evidence"],
            )
        )
    db.flush()
    return created
