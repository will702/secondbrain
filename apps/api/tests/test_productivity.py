"""Phase 2: quick-command parsing, Google Meet / Gmail-draft proposals.
Google and the LLM are always faked — no network, nothing leaves the machine."""

import base64
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents.llm_client import FakeLLMClient
from app.agents.productivity import QuickCommandError, parse_quick_command
from app.agents.router import ModelRouter
from app.main import app
from app.models import ActionProposal, Event, User
from app.models.enums import ProposalStatus
from app.services.integrations import google
from app.services.proposals.service import INDIVIDUAL_ONLY, decide, propose


@pytest.fixture
def client():
    with TestClient(app) as c:
        r = c.post(
            "/auth/register",
            json={"email": "p2@example.com", "password": "correct-horse-1", "display_name": "P2"},
        )
        assert r.status_code in (200, 201), r.text
        yield c


@pytest.fixture
def user(client, db) -> User:
    return db.query(User).one()


def router_for(**intent) -> ModelRouter:
    return ModelRouter(FakeLLMClient(lambda agent, purpose, text: intent))


@pytest.fixture
def google_calls(monkeypatch):
    """Capture every Google request; return canned successful responses."""
    calls = []

    def fake_request(db, user, method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        if "drafts" in url:
            return {"id": "draft-1"}
        return {"id": "gev-1", "hangoutLink": "https://meet.google.com/abc-defg-hij"}

    monkeypatch.setattr(google, "_request", fake_request)
    return calls


def meeting_payload(**extra):
    start = datetime.now(UTC) + timedelta(days=1)
    return {"title": "Sync", "starts_at": start, "ends_at": start + timedelta(minutes=30), **extra}


# ------------------------------------------------------------ quick command


def test_meeting_command_becomes_inert_proposal(db, user):
    r = router_for(
        intent="meeting", title="Sync with Sam", when_text="tomorrow 3pm", duration_minutes=45
    )
    p = parse_quick_command(db, user, "meet Sam tomorrow 3pm for 45m", router=r)
    assert p.action_type == "create_meeting"
    assert p.status == ProposalStatus.pending
    assert p.payload["send_invites"] is False
    s = datetime.fromisoformat(p.payload["starts_at"])
    e = datetime.fromisoformat(p.payload["ends_at"])
    assert e - s == timedelta(minutes=45)
    assert db.query(Event).count() == 0, "parsing must not create anything"


def test_model_cannot_invent_attendees_or_enable_invites(db, user):
    r = router_for(
        intent="meeting",
        title="x",
        when_text="tomorrow 3pm",
        attendees=["sam@example.com", "not an email", "a@b"],
    )
    p = parse_quick_command(db, user, "meet sam@example.com tomorrow 3pm", router=r)
    assert p.payload["attendees"] == ["sam@example.com"]
    assert p.payload["send_invites"] is False


def test_invented_addresses_are_dropped_even_if_valid(db, user):
    r = router_for(
        intent="meeting", title="x", when_text="tomorrow 3pm", attendees=["ghost@evil.co"]
    )
    p = parse_quick_command(db, user, "meet someone tomorrow 3pm", router=r)
    assert p.payload["attendees"] == []
    with pytest.raises(QuickCommandError):
        parse_quick_command(
            db, user, "email my boss",
            router=router_for(intent="email_draft", subject="s", to=["boss@evil.co"]),
        )


def test_model_failure_and_overlong_output_are_clean_errors(db, user):
    boom = FakeLLMClient(lambda *a: {})

    def explode(*a, **k):
        raise RuntimeError("model fell over")

    boom.structured = explode
    with pytest.raises(QuickCommandError) as e1:
        parse_quick_command(db, user, "x", router=ModelRouter(boom))
    assert e1.value.status_code == 503
    with pytest.raises(QuickCommandError) as e2:
        parse_quick_command(db, user, "x", router=router_for(intent="task", title="t" * 400))
    assert e2.value.status_code == 422


@pytest.mark.parametrize(
    "intent",
    [
        {"intent": "meeting", "when_text": "whenever"},
        {"intent": "email_draft", "subject": "hi", "to": ["nope"]},
        {"intent": "unknown"},
    ],
)
def test_unusable_commands_are_refused(db, user, intent):
    with pytest.raises(QuickCommandError):
        parse_quick_command(db, user, "something", router=router_for(**intent))
    assert db.query(ActionProposal).count() == 0


def test_zoom_and_reminder_commands(db, user):
    z = parse_quick_command(
        db, user, "zoom tomorrow 3pm",
        router=router_for(intent="meeting", title="Call", when_text="tomorrow 3pm", wants_zoom=True),
    )
    assert z.payload["provider"] == "zoom" and z.payload["send_invites"] is False
    r = parse_quick_command(
        db, user, "remind me tomorrow 9am to call mum",
        router=router_for(intent="reminder", title="Call mum", when_text="tomorrow 9am"),
    )
    assert r.action_type == "create_reminder" and r.payload["due_at"] is not None


def test_reminder_with_unparseable_time_is_refused(db, user):
    with pytest.raises(QuickCommandError):
        parse_quick_command(
            db, user, "x", router=router_for(intent="reminder", title="t", when_text="whenever")
        )


def test_offline_model_is_503(db, user):
    client = FakeLLMClient(lambda *a: {})
    client.available = lambda: False
    with pytest.raises(QuickCommandError) as exc:
        parse_quick_command(db, user, "x", router=ModelRouter(client))
    assert exc.value.status_code == 503


def test_endpoint_returns_proposal(client, monkeypatch):
    monkeypatch.setattr(
        "app.agents.router._default_router",
        router_for(intent="task", title="Buy milk"),
    )
    r = client.post("/quick-command", json={"text": "remind me to buy milk"})
    assert r.status_code == 200
    assert r.json()["action_type"] == "create_task"
    assert r.json()["status"] == "pending"


# ------------------------------------------------------------ payload rules


def test_payload_validation(db, user):
    with pytest.raises(ValidationError):
        propose(db, user, "create_meeting", meeting_payload(attendees=["bad"]), "r", "t")
    start = datetime.now(UTC)
    with pytest.raises(ValidationError):
        propose(
            db,
            user,
            "create_meeting",
            {"title": "x", "starts_at": start, "ends_at": start - timedelta(hours=1)},
            "r",
            "t",
        )
    with pytest.raises(ValidationError):
        propose(db, user, "create_email_draft", {"to": [], "subject": "s", "body": "b"}, "r", "t")


def test_invites_raise_risk(db, user):
    quiet = propose(db, user, "create_meeting", meeting_payload(), "r", "t")
    loud = propose(
        db,
        user,
        "create_meeting",
        meeting_payload(attendees=["a@b.co"], send_invites=True),
        "r",
        "t",
    )
    assert quiet.risk_level.value == "medium"
    assert loud.risk_level.value == "high"


# ------------------------------------------------------------ execution


def test_default_autonomy_cannot_reach_google(db, user, google_calls):
    assert user.autonomy_level == 1
    p = propose(db, user, "create_meeting", meeting_payload(), "r", "t")
    decide(db, user, p, "approve")
    assert p.status == ProposalStatus.failed
    assert google_calls == []


def test_meeting_creates_event_with_meet_link_and_no_emails(db, user, google_calls):
    user.autonomy_level = 3
    db.commit()
    p = propose(
        db, user, "create_meeting", meeting_payload(attendees=["a@b.co"]), "r", "t"
    )
    decide(db, user, p, "approve")
    assert p.status == ProposalStatus.executed
    assert google_calls[0]["params"]["sendUpdates"] == "none"
    assert google_calls[0]["params"]["conferenceDataVersion"] == 1
    sent = google_calls[0]["json"]
    assert sent["attendees"] == [], "must not drop the meeting onto strangers' calendars unasked"
    assert "Invitees (not emailed): a@b.co" in sent["description"]
    ev = db.query(Event).one()
    assert ev.location == "https://meet.google.com/abc-defg-hij"
    assert ev.provider_event_id == "gev-1"


def test_invites_only_sent_when_flag_set(db, user, google_calls):
    user.autonomy_level = 3
    db.commit()
    p = propose(
        db,
        user,
        "create_meeting",
        meeting_payload(attendees=["a@b.co"], send_invites=True),
        "r",
        "t",
    )
    decide(db, user, p, "approve")
    assert google_calls[0]["params"]["sendUpdates"] == "all"
    assert google_calls[0]["json"]["attendees"] == [{"email": "a@b.co"}]


def test_reexecution_does_not_double_create(db, user, google_calls):
    from app.services.proposals.service import execute

    user.autonomy_level = 3
    db.commit()
    p = propose(db, user, "create_meeting", meeting_payload(), "r", "t")
    decide(db, user, p, "approve")
    execute(db, user, p)
    assert len(google_calls) == 1
    assert db.query(Event).count() == 1


def test_draft_is_saved_never_sent(db, user, google_calls):
    user.autonomy_level = 3
    db.commit()
    p = propose(
        db,
        user,
        "create_email_draft",
        {"to": ["a@b.co"], "subject": "Hello", "body": "Body text"},
        "r",
        "t",
    )
    decide(db, user, p, "approve")
    assert p.status == ProposalStatus.executed
    call = google_calls[0]
    assert call["url"].endswith("/drafts") and "send" not in call["url"]
    raw = base64.urlsafe_b64decode(call["json"]["message"]["raw"]).decode()
    assert "Subject: Hello" in raw and "To: a@b.co" in raw


def test_header_injection_in_subject_is_rejected_at_propose(db, user, google_calls):
    with pytest.raises(ValidationError):
        propose(
            db, user, "create_email_draft",
            {"to": ["a@b.co"], "subject": "Hi\nBcc: evil@x.co", "body": "b"}, "r", "t",
        )
    assert db.query(ActionProposal).count() == 0 and google_calls == []


def test_naive_datetimes_are_rejected(db, user):
    naive = datetime.now() + timedelta(days=1)  # noqa: DTZ005 — the point of the test
    with pytest.raises(ValidationError):
        propose(
            db, user, "create_meeting",
            {"title": "x", "starts_at": naive, "ends_at": naive + timedelta(minutes=30)}, "r", "t",
        )


def test_modify_recomputes_risk(db, user, google_calls):
    user.autonomy_level = 3
    db.commit()
    p = propose(db, user, "create_meeting", meeting_payload(attendees=["a@b.co"]), "r", "t")
    assert p.risk_level.value == "medium"
    decide(db, user, p, "modify", dict(p.payload, send_invites=True))
    assert p.risk_level.value == "high"
    assert google_calls[0]["params"]["sendUpdates"] == "all"


def test_gmail_scope_is_opt_in(monkeypatch):
    from app.core.config import get_settings
    from app.services import calendar as cal

    assert cal.GMAIL_COMPOSE_SCOPE not in cal.google_scopes()
    monkeypatch.setattr(get_settings(), "google_gmail_drafts", True)
    assert cal.GMAIL_COMPOSE_SCOPE in cal.google_scopes()


def test_outward_actions_excluded_from_batch_approve(client, db, user, google_calls):
    assert INDIVIDUAL_ONLY == {"create_meeting", "create_email_draft", "run_shortcut"}
    user.autonomy_level = 3
    db.commit()
    p = propose(db, user, "create_meeting", meeting_payload(), "r", "t")
    r = client.post("/proposals/approve-batch", json={"proposal_ids": [str(p.id)]})
    assert r.json()["results"][0]["status"] == "needs_individual_decision"
    assert google_calls == []


# ------------------------------------------------------------ Zoom / Apple providers


@pytest.fixture
def apple_calls(monkeypatch):
    from app.services.integrations import apple

    calls = []

    def fake_osascript(script, args):
        calls.append(("osascript", args))
        return "id-1"

    monkeypatch.setattr(apple, "_osascript", fake_osascript)
    monkeypatch.setattr(apple, "_require_enabled", lambda: None)
    monkeypatch.setattr(
        apple, "_run", lambda argv: (calls.append(("run", argv)), "Focus\nWork")[1]
    )
    return calls


def test_zoom_meeting_stores_join_link_and_never_claims_invites(db, user, monkeypatch):
    from app.services.integrations import zoom

    user.autonomy_level = 3
    db.commit()
    seen = {}

    def fake_create(**kw):
        seen.update(kw)
        return {"zoom_meeting_id": "99", "join_url": "https://zoom.us/j/99"}

    monkeypatch.setattr(zoom, "create_meeting", fake_create)
    p = propose(
        db, user, "create_meeting",
        meeting_payload(provider="zoom", attendees=["a@b.co"]), "r", "t",
    )
    decide(db, user, p, "approve")
    assert p.status == ProposalStatus.executed
    assert seen["duration_minutes"] == 30
    assert "Invitees (not emailed): a@b.co" in seen["agenda"], "attendees must not vanish silently"
    ev = db.query(Event).one()
    assert ev.provider == "zoom" and ev.location == "https://zoom.us/j/99"


def test_zoom_cannot_request_email_invites(db, user):
    with pytest.raises(ValidationError):
        propose(
            db, user, "create_meeting",
            meeting_payload(provider="zoom", attendees=["a@b.co"], send_invites=True), "r", "t",
        )


def test_reminder_runs_at_default_autonomy(db, user, apple_calls):
    assert user.autonomy_level == 1
    p = propose(db, user, "create_reminder", {"title": "Call mum"}, "r", "t")
    decide(db, user, p, "approve")
    assert p.status == ProposalStatus.executed
    assert apple_calls[0][1][:3] == ["Reminders", "Call mum", ""]


def test_apple_mail_draft_and_calendar(db, user, apple_calls):
    user.autonomy_level = 3
    db.commit()
    d = propose(
        db, user, "create_email_draft",
        {"provider": "apple_mail", "to": ["a@b.co"], "subject": "S", "body": "B"}, "r", "t",
    )
    decide(db, user, d, "approve")
    assert d.status == ProposalStatus.executed
    assert apple_calls[0][1] == ["S", "B", "a@b.co"]
    m = propose(db, user, "create_meeting", meeting_payload(provider="apple_calendar"), "r", "t")
    decide(db, user, m, "approve")
    assert m.status == ProposalStatus.executed
    assert db.query(Event).one().provider == "apple"


def test_shortcut_needs_level_3_and_is_high_risk(db, user, apple_calls):
    p = propose(db, user, "run_shortcut", {"name": "Focus"}, "r", "t")
    assert p.risk_level.value == "high"
    decide(db, user, p, "approve")
    assert p.status == ProposalStatus.failed
    assert apple_calls == []
    user.autonomy_level = 3
    db.commit()
    p2 = propose(db, user, "run_shortcut", {"name": "Focus"}, "r", "t")
    decide(db, user, p2, "approve")
    assert p2.status == ProposalStatus.executed


# ------------------------------------------------------------ adapters (pure)


def test_apple_args_are_data_not_script(monkeypatch):
    from app.services.integrations import apple

    monkeypatch.setattr(apple, "_require_enabled", lambda: None)
    captured = []
    monkeypatch.setattr(
        apple.subprocess,
        "run",
        lambda argv, **kw: (captured.append(argv), type("R", (), {"returncode": 0, "stdout": "x", "stderr": ""})())[1],
    )
    hostile = '-x"; do shell script "rm -rf ~" --'
    apple.create_reminder(title=hostile)
    argv = captured[0]
    assert argv[0] == "osascript" and argv[1] == "-e"
    assert hostile not in argv[2], "user text must never be spliced into script source"
    dash = argv.index("--")
    assert dash > 2 and hostile in argv[dash + 1 :]


def test_apple_disabled_by_default():
    from app.services.integrations import apple

    with pytest.raises(apple.AppleUnavailable):
        apple.create_reminder(title="x")


def test_shortcut_name_must_exist(monkeypatch):
    from app.services.integrations import apple

    monkeypatch.setattr(apple, "_require_enabled", lambda: None)
    monkeypatch.setattr(apple, "_run", lambda argv: "Focus\nWork")
    with pytest.raises(apple.AppleUnavailable):
        apple.run_shortcut("Delete Everything")
    with pytest.raises(apple.AppleUnavailable):
        apple.run_shortcut("-h")


def test_zoom_unconfigured_is_unavailable():
    from app.services.integrations import zoom

    with pytest.raises(zoom.ZoomUnavailable):
        zoom.create_meeting(
            topic="t", starts_at=datetime.now(UTC), duration_minutes=30, timezone="UTC"
        )
