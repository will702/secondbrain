"""Phase 4: goals + ambition engine. LLM is always faked."""

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.agents.llm_client import FakeLLMClient
from app.agents.router import ModelRouter
from app.main import app
from app.models import ActionProposal, Event, Goal, Task, User
from app.models.enums import EventKind, GoalHorizon, ProposalStatus, TaskStatus
from app.services.goals import service as goals
from app.services.proposals.service import decide


def _register(c: TestClient, email: str):
    r = c.post("/auth/register", json={"email": email, "password": "correct-horse-1", "display_name": "G"})
    assert r.status_code in (200, 201), r.text


@pytest.fixture
def client():
    with TestClient(app) as c:
        _register(c, "goals@example.com")
        yield c


@pytest.fixture
def user(client, db) -> User:
    return db.query(User).filter(User.email == "goals@example.com").one()


def offline_router() -> ModelRouter:
    c = FakeLLMClient(lambda *a: {})
    c.available = lambda: False
    return ModelRouter(c)


def make_goal(db, user, *, target=3, title="G", weeks_ago=0, metric="tasks") -> Goal:
    monday, sunday = goals.week_bounds(goals.local_today(user) - timedelta(weeks=weeks_ago))
    g = Goal(
        user_id=user.id, title=title, horizon=GoalHorizon.week, metric=metric,
        target_value=target, starts_on=monday, due_on=sunday,
    )
    db.add(g)
    db.commit()
    return g


def make_task(db, user, *, goal=None, done=False, minutes=30, title="T") -> Task:
    t = Task(
        user_id=user.id, title=title, goal_id=goal.id if goal else None,
        status=TaskStatus.done if done else TaskStatus.pending,
        completed_at=datetime.now(UTC) if done else None, estimated_minutes=minutes,
    )
    db.add(t)
    db.commit()
    return t


# ------------------------------------------------------------ pure logic


def test_scale_target_shrinks_when_busy_but_never_zero():
    free_week = goals.scale_target(3, 1.0)
    normal_week = goals.scale_target(3, goals.TYPICAL_FREE)
    busy_week = goals.scale_target(3, 0.05)
    slammed = goals.scale_target(3, 0.0)
    assert free_week >= normal_week > busy_week >= goals.MIN_TARGET
    assert slammed == goals.MIN_TARGET
    assert normal_week == 4  # ceil(3 * 1.1 * 1.0): a gentle stretch over baseline


def test_pace():
    assert goals.pace(1.0, 0.2) == "done"
    assert goals.pace(0.9, 0.5) == "ahead"
    assert goals.pace(0.5, 0.5) == "on_track"
    assert goals.pace(0.1, 0.8) == "behind"


def test_streak_stops_at_miss_or_gap():
    assert goals.streak([1.0, 0.9, 0.8, 0.2, 1.0]) == 3
    assert goals.streak([0.79, 1.0]) == 0
    assert goals.streak([1.0, None, 1.0]) == 1
    assert goals.streak([]) == 0


def test_week_bounds_monday_to_sunday():
    mon, sun = goals.week_bounds(date(2026, 11, 4))  # a Wednesday
    assert (mon.weekday(), sun.weekday()) == (0, 6)
    assert (sun - mon).days == 6


# ------------------------------------------------------------ progress


def test_progress_counts_only_own_linked_done_tasks_and_checkins(client, db, user):
    g = make_goal(db, user, target=4)
    make_task(db, user, goal=g, done=True)
    make_task(db, user, goal=g, done=True)
    make_task(db, user, goal=g, done=False)  # not done
    make_task(db, user, goal=None, done=True)  # not linked
    client.post(f"/goals/{g.id}/checkin", json={"delta": 1})
    v = goals.goal_view(db, user, g)
    assert v["current"] == 3 and v["pct"] == 0.75


def test_task_done_outside_goal_window_is_ignored(db, user):
    g = make_goal(db, user, target=2)
    t = make_task(db, user, goal=g, done=True)
    t.completed_at = datetime.now(UTC) - timedelta(days=60)
    db.commit()
    assert goals.current_value(db, user, g) == 0


def test_non_task_metric_ignores_tasks(client, db, user):
    g = make_goal(db, user, target=10, metric="pages")
    make_task(db, user, goal=g, done=True)
    client.post(f"/goals/{g.id}/checkin", json={"delta": 4})
    assert goals.current_value(db, user, g) == 4


def test_complete_task_is_idempotent_and_sets_timestamp(client, db, user):
    t = make_task(db, user)
    assert client.post(f"/tasks/{t.id}/complete").json()["status"] == "done"
    db.expire_all()
    first = db.get(Task, t.id).completed_at
    client.post(f"/tasks/{t.id}/complete")
    db.expire_all()
    assert first is not None and db.get(Task, t.id).completed_at == first


def test_cannot_touch_other_users_goal_or_task(client, db, user):
    g = make_goal(db, user)
    t = make_task(db, user)
    with TestClient(app) as other:
        _register(other, "intruder@example.com")
        assert other.post(f"/goals/{g.id}/checkin", json={"delta": 1}).status_code == 404
        assert other.post(f"/tasks/{t.id}/complete").status_code == 404
        mine = other.post("/goals", json={"title": "mine", "target_value": 2}).json()
        # linking someone else's task, or my task to someone else's goal, both 404
        assert other.post(f"/tasks/{t.id}/goal", json={"goal_id": mine["id"]}).status_code == 404
    assert client.post(f"/tasks/{t.id}/goal", json={"goal_id": mine["id"]}).status_code == 404


def test_checkin_rejects_zero(client, db, user):
    g = make_goal(db, user)
    assert client.post(f"/goals/{g.id}/checkin", json={"delta": 0}).status_code == 422


# ------------------------------------------------------------ suggestions


def test_suggest_without_model_still_proposes_and_dedups(db, user):
    first = goals.propose_targets(db, user, router=offline_router())
    assert len(first) == 1
    p = first[0]
    assert p.status == ProposalStatus.pending and p.action_type == "create_goal"
    assert p.payload["target_value"] >= goals.MIN_TARGET
    assert goals.propose_targets(db, user, router=offline_router()) == [], "no duplicate asks"
    assert db.query(Goal).count() == 0, "suggestions are inert until approved"


def test_model_ideas_get_split_targets_but_model_never_sets_numbers(db, user):
    ideas = {"ideas": [{"title": "Ship report", "why": "x"}, {"title": "Clear inbox", "why": "y"}]}
    router = ModelRouter(FakeLLMClient(lambda *a: ideas))
    made = goals.propose_targets(db, user, router=router)
    assert {m.payload["title"] for m in made} == {"Ship report", "Clear inbox"}
    total = made[0].evidence["total_target"]
    assert sum(m.payload["target_value"] for m in made) >= total
    assert all(m.payload["target_value"] >= goals.MIN_TARGET for m in made)


def test_approving_suggestion_creates_goal(db, user):
    p = goals.propose_targets(db, user, router=offline_router())[0]
    decide(db, user, p, "approve")
    assert p.status == ProposalStatus.executed
    g = db.query(Goal).one()
    assert g.source == "ambition-engine" and g.horizon == GoalHorizon.week


def test_busy_week_gets_smaller_but_nonzero_target(db, user):
    free = goals.propose_targets(db, user, router=offline_router())[0].payload["target_value"]
    db.query(ActionProposal).delete()
    db.commit()
    start = datetime.now(UTC) + timedelta(hours=1)
    for i in range(8):  # ~80h booked of ~91h work time in the next 7 days
        s = start + timedelta(hours=18 * i)
        db.add(Event(user_id=user.id, kind=EventKind.hard, title=f"m{i}", starts_at=s,
                     ends_at=s + timedelta(hours=10), timezone=user.timezone))
    db.commit()
    busy = goals.propose_targets(db, user, router=offline_router())[0].payload["target_value"]
    assert goals.MIN_TARGET <= busy < free


# ------------------------------------------------------------ streak, briefing, review


def test_weekly_streak_from_history(client, db, user):
    for weeks_ago in (1, 2):
        g = make_goal(db, user, target=2, weeks_ago=weeks_ago, title=f"w{weeks_ago}")
        client.post(f"/goals/{g.id}/checkin", json={"delta": 2})
    make_goal(db, user, target=2, weeks_ago=4, title="old")  # gap at 3 weeks ago breaks it
    assert goals.weekly_streak(db, user) == 2


def test_briefing_has_ambition_with_todays_move(client, db, user):
    g = make_goal(db, user, target=3)
    t = make_task(db, user, goal=g, minutes=30, title="Write section 2")
    make_task(db, user, goal=None, minutes=30, title="Unrelated")
    b = client.get("/briefing").json()["ambition"]
    assert [x["title"] for x in b["goals"]] == ["G"]
    assert b["todays_move"]["task_id"] == str(t.id)
    assert b["nudge"]


def test_briefing_without_goals_nudges_to_set_one(client):
    b = client.get("/briefing").json()["ambition"]
    assert b["goals"] == [] and b["todays_move"] is None
    assert "target" in b["nudge"].lower()


def test_weekly_review_shape(client, db, user):
    g = make_goal(db, user, target=4)
    client.post(f"/goals/{g.id}/checkin", json={"delta": 2})
    r = client.get("/goals/review").json()
    assert r["planned"] == 4 and r["done"] == 2 and r["completion"] == 0.5
    assert r["next_week"]["suggested_total_target"] >= goals.MIN_TARGET


def test_observer_cannot_mutate_goals_or_tasks(client, db, user):
    g = make_goal(db, user)
    t = make_task(db, user)
    user.autonomy_level = 0
    db.commit()
    assert client.post(f"/goals/{g.id}/checkin", json={"delta": 1}).status_code == 403
    assert client.post(f"/goals/{g.id}/status", json={"status": "dropped"}).status_code == 403
    assert client.post(f"/tasks/{t.id}/complete").status_code == 403
    assert client.post(f"/tasks/{t.id}/goal", json={"goal_id": str(g.id)}).status_code == 403
    assert client.get("/goals").status_code == 200, "reading stays allowed"


def test_pending_suggestions_are_not_piled_up_even_with_different_ideas(db, user):
    first = ModelRouter(FakeLLMClient(lambda *a: {"ideas": [{"title": "Idea A"}]}))
    second = ModelRouter(FakeLLMClient(lambda *a: {"ideas": [{"title": "Idea B"}]}))
    assert len(goals.propose_targets(db, user, router=first)) == 1
    assert goals.propose_targets(db, user, router=second) == []
    assert db.query(ActionProposal).count() == 1


def test_approving_goal_tolerates_existing_duplicates(db, user):
    title = "Finish my priority tasks this week"
    p = goals.propose_targets(db, user, router=offline_router())[0]
    assert p.payload["title"] == title
    # ...then the same goal gets created by hand twice before the suggestion is approved.
    make_goal(db, user, title=title)
    make_goal(db, user, title=title)
    decide(db, user, p, "approve")
    assert p.status == ProposalStatus.executed, "must not crash on MultipleResultsFound"
