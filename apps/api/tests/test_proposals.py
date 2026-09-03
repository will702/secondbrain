"""M5: policy layer, proposal lifecycle, briefing/attention/readiness."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    ActionExecution,
    ActionProposal,
    AuditLog,
    Deadline,
    Event,
    Task,
    User,
)
from app.models.enums import EventKind, ProposalStatus, TaskStatus
from app.services.policy import check
from app.services.proposals.service import decide, propose


class FakeUser:
    """policy.check only reads autonomy_level — a lightweight stand-in is honest here."""

    def __init__(self, level: int):
        self.autonomy_level = level


def test_policy_matrix():
    observer = FakeUser(0)
    assert check(observer, "task.create").allowed is False
    assert check(observer, "note.create").allowed is False

    assistant = FakeUser(1)
    assert check(assistant, "task.create").allowed is True
    assert check(assistant, "event.write_soft").allowed is False
    assert check(assistant, "event.write_hard").allowed is False

    planner = FakeUser(2)
    assert check(planner, "event.write_soft").allowed is True
    assert check(planner, "event.write_hard").allowed is False

    copilot = FakeUser(3)
    assert check(copilot, "event.write_hard").allowed is True
    assert check(copilot, "email.draft").allowed is True


def test_danger_actions_always_confirm():
    for level in range(5):
        decision = check(FakeUser(level), "send_email")
        assert decision.requires_confirmation is True
        assert "danger" in decision.reason


def test_level4_skips_confirmation_for_normal_actions():
    assert check(FakeUser(4), "task.create").requires_confirmation is False
    assert check(FakeUser(3), "task.create").requires_confirmation is True


@pytest.fixture
def m5_client(db, fake_embeddings):
    with TestClient(app) as client:
        client.post(
            "/auth/register",
            json={"email": "m5@test.dev", "password": "password-123", "display_name": "M5"},
        )
        yield client


def _user(db) -> User:
    return db.query(User).filter_by(email="m5@test.dev").one()


def test_proposal_lifecycle_approve_creates_event_and_audit(m5_client, db):
    user = _user(db)
    user.autonomy_level = 2  # may write soft events
    db.commit()

    proposal = propose(
        db, user, "create_event",
        {
            "title": "Focus: Assignment 4",
            "starts_at": "2026-09-10T19:00:00+07:00",
            "ends_at": "2026-09-10T21:00:00+07:00",
            "kind": "focus",
        },
        reason="Deadline Friday, estimated 3h remaining.",
        proposed_by="planning",
        evidence={"task_id": "t"},
    )
    assert proposal.status == ProposalStatus.pending

    response = m5_client.post(
        f"/proposals/{proposal.id}/decide", json={"decision": "approve"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "executed"

    event = db.query(Event).filter_by(title="Focus: Assignment 4").one()
    assert event.kind == EventKind.focus
    assert str(event.source_proposal_id) == str(proposal.id)

    execution = db.query(ActionExecution).filter_by(proposal_id=proposal.id).one()
    assert execution.status == "success"
    audit_actions = [a.action for a in db.query(AuditLog).all()]
    assert "proposal.approve" in audit_actions
    assert "proposal.execute.create_event" in audit_actions


def test_proposal_modify_flow(m5_client, db):
    user = _user(db)
    proposal = propose(
        db, user, "create_task",
        {"title": "Draft proposal", "estimated_minutes": 120, "priority": 2},
        reason="Commitment detected in email.",
        proposed_by="mail",
    )
    response = m5_client.post(
        f"/proposals/{proposal.id}/decide",
        json={
            "decision": "modify",
            "modified_payload": {"title": "Draft proposal v2", "estimated_minutes": 90,
                                 "priority": 1},
        },
    )
    assert response.status_code == 200
    task = db.query(Task).filter_by(title="Draft proposal v2").one()
    assert task.priority == 1 and task.estimated_minutes == 90


def test_proposal_reject_leaves_no_side_effects(m5_client, db):
    user = _user(db)
    proposal = propose(
        db, user, "create_task",
        {"title": "Rejected task", "priority": 3},
        reason="test",
        proposed_by="planning",
    )
    m5_client.post(f"/proposals/{proposal.id}/decide", json={"decision": "reject"})
    db.expire_all()  # the client's session committed; drop our stale identity map
    assert db.query(Task).filter_by(title="Rejected task").count() == 0
    assert db.query(ActionExecution).filter_by(proposal_id=proposal.id).count() == 0
    assert db.get(ActionProposal, proposal.id).status == ProposalStatus.rejected


def test_invalid_payload_rejected_at_proposal_time(db, m5_client):
    from pydantic import ValidationError

    user = _user(db)
    with pytest.raises(ValidationError):
        propose(db, user, "create_task", {"title": ""}, reason="x", proposed_by="t")


def test_proposals_inert_until_user_approval(db, m5_client):
    """Even at Observer level (0), a proposal may exist — but nothing executes
    until the user explicitly approves. That is the permission wall."""
    user = _user(db)
    user.autonomy_level = 0
    db.commit()
    proposal = propose(
        db, user, "create_event",
        {"title": "Suggested block", "starts_at": "2026-09-10T19:00:00+07:00",
         "ends_at": "2026-09-10T20:00:00+07:00", "kind": "focus"},
        reason="planner suggestion", proposed_by="planning",
    )
    assert proposal.status == ProposalStatus.pending
    assert db.query(Event).count() == 0  # inert: nothing happened yet
    decided = decide(db, user, proposal, "approve")  # user intent = authorization
    assert decided.status == ProposalStatus.executed
    assert db.query(Event).count() == 1


def test_batch_approve(m5_client, db):
    user = _user(db)
    ids = []
    for i in range(3):
        proposal = propose(
            db, user, "create_task",
            {"title": f"Batch task {i}", "priority": 3},
            reason="batch test", proposed_by="planning",
        )
        ids.append(str(proposal.id))
    response = m5_client.post("/proposals/approve-batch", json={"proposal_ids": ids})
    results = response.json()["results"]
    assert all(r["status"] == "executed" for r in results)
    assert db.query(Task).filter(Task.title.like("Batch task%")).count() == 3


def test_level1_recompute_creates_proposals_not_events(m5_client, db):
    """The killer loop at default autonomy: plan → proposals → approve → events."""
    user = _user(db)
    assert user.autonomy_level == 1  # default
    db.add(Task(user_id=user.id, title="Prepare slides", estimated_minutes=120,
                minimum_session_minutes=60))
    db.commit()

    result = m5_client.post("/schedule/recompute").json()
    assert result["applied"] is False
    assert result["proposals"] >= 1
    assert db.query(Event).filter_by(kind=EventKind.focus).count() == 0  # nothing forced

    pending = m5_client.get("/proposals", params={"status_filter": "pending"}).json()
    assert len(pending) >= 1

    approved = m5_client.post(
        "/proposals/approve-batch",
        json={"proposal_ids": [p["id"] for p in pending]},
    ).json()
    assert all(r["status"] == "executed" for r in approved["results"])
    assert db.query(Event).filter_by(kind=EventKind.focus).count() >= 1


def test_briefing_structure_and_attention(m5_client, db):
    user = _user(db)
    soon = datetime.now(UTC) + timedelta(hours=30)
    db.add(Deadline(
        user_id=user.id, title="Midterm", normalized_at=soon, date_is_exact=True,
        raw_expression="October 20", timezone=user.timezone, confidence=0.9,
        explicit=True, status="confirmed",
        provenance={"document_id": "test"},
    ))
    db.add(Task(user_id=user.id, title="Study for midterm", estimated_minutes=300,
                priority=1, importance=0.9))
    db.commit()

    briefing = m5_client.get("/briefing").json()
    assert briefing["greeting"].startswith("Good")
    assert briefing["top_priorities"], "attention engine must surface the urgent task"
    top = briefing["top_priorities"][0]
    assert "Study for midterm" == top["title"]
    assert top["why"]  # every priority is explainable
    assert briefing["upcoming"]["3_days"] == 1
    assert any("hasn't been started" in r["message"] for r in briefing["risks"])
    readiness = briefing["readiness"]
    assert readiness and readiness[0]["title"] == "Midterm"
    assert 0 <= readiness[0]["score"] <= 100
    assert readiness[0]["components"]["tasks_completed"] == "0/1"
    assert any("free block" in s["action"] or "Work on" in s["action"]
               for s in briefing["suggestions"])
