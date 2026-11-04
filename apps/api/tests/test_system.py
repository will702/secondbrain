"""System visibility + PMAX bridge. The pmax binary is always faked: these
tests must never touch real files or require the Go binary."""

import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import AuditLog, Event, User
from app.models.enums import EventKind
from app.services import system_status
from app.services.integrations import pmax

PLAN = "plan-20260101-120000-42.tsv"
ROW = "0123456789abcdef"


def _login(client: TestClient) -> User:
    r = client.post(
        "/auth/register",
        json={"email": "sys@example.com", "password": "correct-horse-1", "display_name": "Sys"},
    )
    assert r.status_code in (200, 201), r.text
    return r


@pytest.fixture
def client():
    with TestClient(app) as c:
        _login(c)
        yield c


def test_load_level_thresholds():
    assert system_status.load_level(0) == "light"
    assert system_status.load_level(50) == "normal"
    assert system_status.load_level(70) == "heavy"


def test_status_survives_missing_pmax(client, monkeypatch):
    monkeypatch.setattr(pmax, "pmax_bin", lambda: None)
    r = client.get("/system/status")
    assert r.status_code == 200
    assert r.json()["pmax"]["available"] is False


def test_pending_503_when_pmax_missing(client, monkeypatch):
    monkeypatch.setattr(pmax, "pmax_bin", lambda: None)
    assert client.get("/pmax/pending").status_code == 503


@pytest.mark.parametrize(
    "plan,row",
    [("../etc/passwd", ROW), (PLAN, "nothex"), ("plan-x.tsv;rm -rf", ROW), ("notaplan.tsv", ROW)],
)
def test_decide_row_validates_before_argv(monkeypatch, plan, row):
    calls = []
    monkeypatch.setattr(pmax, "_run", lambda args: calls.append(args))
    with pytest.raises(pmax.PmaxRejected):
        pmax.decide_row(plan, row, True)
    assert calls == [], "invalid input must never reach the subprocess"


def test_decide_row_passes_exactly_one_row(monkeypatch):
    seen = []

    def fake_run(args):
        seen.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(pmax, "_run", fake_run)
    pmax.decide_row(PLAN, ROW, True)
    pmax.decide_row(PLAN, ROW, False)
    assert seen == [["approve-one", PLAN, ROW], ["reject-one", PLAN, ROW]]


def test_approve_endpoint_audits_and_maps_refusal(client, db, monkeypatch):
    monkeypatch.setattr(
        pmax, "_run", lambda args: subprocess.CompletedProcess(args, 0, "", "")
    )
    r = client.post(f"/pmax/pending/{PLAN}/{ROW}/approve")
    assert r.status_code == 200
    log = db.query(AuditLog).filter(AuditLog.action == "pmax.approve").one()
    assert log.object_id == ROW and log.detail == {"plan": PLAN}

    monkeypatch.setattr(
        pmax, "_run", lambda args: subprocess.CompletedProcess(args, 1, "", "stale id")
    )
    r = client.post(f"/pmax/pending/{PLAN}/{ROW}/approve")
    assert r.status_code == 409


def test_cross_origin_decision_refused(client, monkeypatch):
    called = []
    monkeypatch.setattr(pmax, "_run", lambda args: called.append(args))
    r = client.post(
        f"/pmax/pending/{PLAN}/{ROW}/approve", headers={"Origin": "https://evil.example"}
    )
    assert r.status_code == 403
    assert called == []


def test_decisions_require_login():
    with TestClient(app) as anon:
        assert anon.post(f"/pmax/pending/{PLAN}/{ROW}/approve").status_code == 401
        assert anon.get("/system/status").status_code == 401


def test_load_counts_booked_time(client, db):
    user = db.query(User).one()
    start = datetime.now(UTC) + timedelta(hours=1)
    db.add(
        Event(
            user_id=user.id,
            kind=EventKind.hard,
            title="Big meeting",
            starts_at=start,
            ends_at=start + timedelta(hours=3),
            timezone=user.timezone,
        )
    )
    db.commit()
    load = client.get("/system/load").json()
    assert load["week"]["booked_minutes"] == 180
    assert load["today"]["booked_pct"] > load["week"]["booked_pct"]


def test_activity_feed_is_newest_first(client, db):
    user = db.query(User).one()
    for i in range(3):
        db.add(AuditLog(user_id=user.id, actor="user", action=f"a{i}"))
        db.commit()
    items = client.get("/system/activity?limit=2").json()["items"]
    assert len(items) == 2
    assert items[0]["at"] >= items[1]["at"]


def test_load_snapshot_written_atomically_for_pmax(tmp_path, monkeypatch):
    import json

    monkeypatch.setenv("PMAX_STATE", str(tmp_path))
    load = {"today": {"level": "heavy", "booked_pct": 82}, "week": {"level": "normal"}}
    assert pmax.write_load_snapshot(load) is True
    data = json.loads((tmp_path / "load.json").read_text())
    assert data["level"] == "heavy" and data["today_booked_pct"] == 82
    datetime.fromisoformat(data["generated_at"])  # PMAX parses this as RFC3339
    assert not (tmp_path / "load.json.tmp").exists()


def test_load_snapshot_skipped_when_pmax_not_installed(tmp_path, monkeypatch):
    monkeypatch.setenv("PMAX_STATE", str(tmp_path / "missing"))
    load = {"today": {"level": "light", "booked_pct": 5}, "week": {"level": "light"}}
    assert pmax.write_load_snapshot(load) is False
    assert not (tmp_path / "missing").exists(), "must not create PMAX's state dir"


def test_opening_system_load_refreshes_snapshot(client, tmp_path, monkeypatch):
    monkeypatch.setenv("PMAX_STATE", str(tmp_path))
    assert client.get("/system/load").status_code == 200
    assert (tmp_path / "load.json").exists()


def test_only_the_instance_owner_can_use_the_pmax_bridge(client, tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(pmax, "_run", lambda args: called.append(args))
    monkeypatch.setenv("PMAX_STATE", str(tmp_path))
    with TestClient(app) as guest:  # registered after the owner
        guest.post(
            "/auth/register",
            json={"email": "guest@example.com", "password": "correct-horse-1", "display_name": "G"},
        )
        assert guest.get("/pmax/pending").status_code == 403
        assert guest.post(f"/pmax/pending/{PLAN}/{ROW}/approve").status_code == 403
        assert guest.post(f"/pmax/pending/{PLAN}/{ROW}/reject").status_code == 403
        assert guest.get("/system/status").json()["pmax"] == {
            "available": False, "error": "owner only",
        }
        guest.get("/system/load")
    assert called == [], "a non-owner must never reach the pmax binary"
    assert not (tmp_path / "load.json").exists(), "a non-owner must not drive PMAX's behaviour"
