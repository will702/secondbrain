"""M4: planner constraints, calendar, ics round-trip, rescheduling."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import AIDecision, Event, Task, User
from app.models.enums import EventKind, TaskStatus
from app.services.scheduling.planner import Interval, Planner, PlannerTask, merge_intervals

TZ = "Asia/Jakarta"
MONDAY = datetime(2026, 9, 7, 0, 0, tzinfo=ZoneInfo(TZ))  # a clean Monday
FRIDAY = MONDAY + timedelta(days=4)


def make_planner() -> Planner:
    return Planner(work_start=time(9, 0), work_end=time(22, 0), tz_name=TZ)


# ----------------------------------------------------------------- planner unit tests

def test_merge_intervals():
    merged = merge_intervals(
        [
            Interval(MONDAY.replace(hour=9), MONDAY.replace(hour=11)),
            Interval(MONDAY.replace(hour=10), MONDAY.replace(hour=12)),
            Interval(MONDAY.replace(hour=14), MONDAY.replace(hour=15)),
        ]
    )
    assert len(merged) == 2
    assert merged[0].end.hour == 12


def test_exam_prep_spreads_before_deadline():
    """Exam Friday → preparation staged across Mon–Thu, not crammed Thursday night."""
    exam_event = Event(
        user_id=None, kind=EventKind.deadline, title="Midterm",
        starts_at=FRIDAY.replace(hour=13), ends_at=FRIDAY.replace(hour=15),
        timezone=TZ,
    )
    prep = PlannerTask(
        id="prep", title="Midterm preparation", priority=1,
        estimated_minutes=8 * 60, minimum_session_minutes=60,
        deadline=FRIDAY.replace(hour=13),
    )
    plan = make_planner().plan([prep], [exam_event], now=MONDAY.replace(hour=8))
    days = {s.start.date().isoformat() for s in plan.sessions}
    assert "2026-09-07" in days  # starts Monday
    assert "2026-09-11" not in days  # nothing on exam day
    assert len(plan.sessions) >= 4  # staged across days
    assert all(s.end <= FRIDAY.replace(hour=13) for s in plan.sessions)
    total = sum((s.end - s.start).total_seconds() for s in plan.sessions) / 60
    assert total == 8 * 60


def test_hard_events_never_overlapped():
    busy_event = Event(
        user_id=None, kind=EventKind.hard, title="Team meeting",
        starts_at=MONDAY.replace(hour=10), ends_at=MONDAY.replace(hour=12), timezone=TZ,
    )
    task = PlannerTask(id="t1", title="Task", estimated_minutes=120, minimum_session_minutes=60)
    plan = make_planner().plan([task], [busy_event], now=MONDAY.replace(hour=8))
    busy = Interval(MONDAY.replace(hour=10), MONDAY.replace(hour=12))
    for session in plan.sessions:
        assert not (
            session.start < busy.end and busy.start < session.end
        ), f"session {session.start}–{session.end} overlaps the hard event"


def test_min_session_length_respected():
    task = PlannerTask(id="t", title="Deep work", estimated_minutes=90, minimum_session_minutes=90)
    plan = make_planner().plan([task], [], now=MONDAY.replace(hour=8))
    sessions = [s for s in plan.sessions if s.task_id == "t"]
    assert len(sessions) == 1
    assert (sessions[0].end - sessions[0].start).total_seconds() / 60 == 90


def test_dependency_ordering():
    base = PlannerTask(id="base", title="Research", estimated_minutes=60, minimum_session_minutes=60)
    dependent = PlannerTask(
        id="later", title="Write-up", estimated_minutes=60, minimum_session_minutes=60,
        depends_on=["base"],
    )
    plan = make_planner().plan([dependent, base], [], now=MONDAY.replace(hour=8))
    base_end = max(s.end for s in plan.sessions if s.task_id == "base")
    later_start = min(s.start for s in plan.sessions if s.task_id == "later")
    assert later_start >= base_end


def test_infeasible_when_deadline_too_close():
    task = PlannerTask(
        id="doomed", title="Big task", estimated_minutes=10 * 60,
        minimum_session_minutes=60, deadline=MONDAY.replace(hour=13),
    )
    # Work day already half full.
    busy = Event(
        user_id=None, kind=EventKind.hard, title="Class",
        starts_at=MONDAY.replace(hour=9), ends_at=MONDAY.replace(hour=12), timezone=TZ,
    )
    plan = make_planner().plan([task], [busy], now=MONDAY.replace(hour=8))
    assert "doomed" in plan.infeasible
    assert any("deadline" in d["reason"] for d in plan.decisions)


def test_preferred_time_of_day():
    task = PlannerTask(
        id="night", title="Study", estimated_minutes=60, minimum_session_minutes=60,
        preferred_time_of_day="evening",
    )
    plan = make_planner().plan([task], [], now=MONDAY.replace(hour=8))
    session = next(s for s in plan.sessions if s.task_id == "night")
    assert session.start.hour >= 18


def test_focus_cap_per_day():
    tasks = [
        PlannerTask(id=f"t{i}", title=f"T{i}", estimated_minutes=4 * 60,
                    minimum_session_minutes=60)
        for i in range(3)
    ]
    plan = make_planner().plan(tasks, [], now=MONDAY.replace(hour=8))
    by_day: dict = {}
    for session in plan.sessions:
        day = session.start.date()
        by_day[day] = by_day.get(day, 0) + (session.end - session.start).total_seconds() / 60
    assert all(minutes <= 6 * 60 for minutes in by_day.values())


# ----------------------------------------------------------------- API integration

@pytest.fixture
def cal_client(db, fake_embeddings):
    with TestClient(app) as client:
        client.post(
            "/auth/register",
            json={"email": "cal@test.dev", "password": "password-123", "display_name": "Cal"},
        )
        yield client


def _create_task(db, user, title, minutes=120, priority=3) -> Task:
    task = Task(
        user_id=user.id, title=title, estimated_minutes=minutes,
        minimum_session_minutes=60, priority=priority,
    )
    db.add(task)
    db.commit()
    return task


def test_recompute_creates_focus_events_and_decisions(cal_client, db):
    user = db.query(User).filter_by(email="cal@test.dev").one()
    user.autonomy_level = 2  # Planner: recompute may write focus blocks directly
    db.commit()
    _create_task(db, user, "Write report", minutes=180, priority=2)

    response = cal_client.post("/schedule/recompute")
    assert response.status_code == 200
    body = response.json()
    assert body["applied"] is True
    assert body["sessions"] >= 1

    events = cal_client.get("/calendar").json()
    focus = [e for e in events if e["kind"] == "focus"]
    assert focus and all(e["title"].startswith("Focus:") for e in focus)
    assert db.query(AIDecision).filter_by(agent="planning").count() >= 1

    task = db.query(Task).filter_by(title="Write report").one()
    assert task.status == TaskStatus.scheduled


def test_missed_session_reschedules_without_touching_hard(cal_client, db):
    user = db.query(User).filter_by(email="cal@test.dev").one()
    user.autonomy_level = 2  # Planner
    db.commit()
    _create_task(db, user, "Prepare demo", minutes=240, priority=1)
    # A hard event Thursday evening.
    hard = cal_client.post(
        "/events",
        json={
            "title": "Family dinner",
            "starts_at": (MONDAY + timedelta(days=3)).replace(hour=19).isoformat(),
            "ends_at": (MONDAY + timedelta(days=3)).replace(hour=21).isoformat(),
            "kind": "hard",
        },
    )
    assert hard.status_code == 201

    first = cal_client.post("/schedule/recompute").json()
    assert first["sessions"] >= 2

    focus_events = [e for e in cal_client.get("/calendar").json() if e["kind"] == "focus"]
    missed_id = focus_events[0]["id"]
    remaining_before = len(focus_events) - 1

    result = cal_client.post(f"/schedule/missed/{missed_id}").json()
    assert result["applied"] is True

    after = [e for e in cal_client.get("/calendar").json() if e["kind"] == "focus"]
    # All 240 minutes still planned across the remaining sessions (or more).
    total_after = sum(
        (datetime.fromisoformat(e["ends_at"]) - datetime.fromisoformat(e["starts_at"])).total_seconds() / 60
        for e in after
    )
    assert total_after >= 240
    # Hard event untouched.
    hard_after = [e for e in cal_client.get("/calendar").json() if e["title"] == "Family dinner"]
    assert len(hard_after) == 1


def test_ics_round_trip(cal_client):
    ics = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "BEGIN:VEVENT",
            "UID:test-1@secondbrain",
            "SUMMARY:Hackathon team meeting",
            f"DTSTART:{FRIDAY.strftime('%Y%m%dT%H%M%S')}Z",
            f"DTEND:{(FRIDAY + timedelta(hours=2)).strftime('%Y%m%dT%H%M%S')}Z",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )
    imported = cal_client.post(
        "/calendar/import-ics",
        files=[("file", ("events.ics", ics.encode(), "text/calendar"))],
    ).json()
    assert imported["imported"] == 1

    # Re-import dedupes by UID.
    again = cal_client.post(
        "/calendar/import-ics",
        files=[("file", ("events.ics", ics.encode(), "text/calendar"))],
    ).json()
    assert again["imported"] == 0 and again["skipped"] == 1

    export = cal_client.get("/calendar/export.ics").text
    assert "Hackathon team meeting" in export


def test_google_dormant_without_credentials(cal_client):
    status = cal_client.get("/calendar/google/status").json()
    assert status["configured"] is False
    connect = cal_client.get("/auth/google/connect")
    assert connect.status_code == 503
    sync = cal_client.post("/calendar/google/sync")
    assert sync.status_code == 409


def test_event_overlap_conflict_detected(cal_client):
    payload = {
        "title": "Class A",
        "starts_at": MONDAY.replace(hour=10).isoformat(),
        "ends_at": MONDAY.replace(hour=12).isoformat(),
        "kind": "hard",
    }
    assert cal_client.post("/events", json=payload).status_code == 201
    clash = cal_client.post(
        "/events",
        json={
            "title": "Class B",
            "starts_at": MONDAY.replace(hour=11).isoformat(),
            "ends_at": MONDAY.replace(hour=13).isoformat(),
            "kind": "hard",
        },
    )
    assert clash.status_code == 409
    assert "Class A" in clash.json()["detail"]
