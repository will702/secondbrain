"""M3: hybrid retrieval + ASK with deterministic intent routing."""

import pytest
from fastapi.testclient import TestClient

from app.agents.ask_agent import classify_intent
from app.main import app

pytestmark = pytest.mark.usefixtures("fake_embeddings")


@pytest.fixture
def ask_client(db, fake_embeddings):
    # Wire a narrating FakeLLM so the LLM path (not the fallback) is exercised.
    from app.agents.llm_client import FakeLLMClient
    from app.agents.router import set_router

    set_router(FakeLLMClient(_synth_responder()))
    import app.services.ingestion.extract_stage as stage

    original = stage.llm_available
    stage.llm_available = lambda: True
    with TestClient(app) as client:
        client.post(
            "/auth/register",
            json={"email": "ask@test.dev", "password": "password-123", "display_name": "Ask"},
        )
        # Ingest the syllabus corpus (extraction returns nothing extra — facts
        # for ASK come from the deadline rows we insert below).
        from app.agents.router import ModelRouter
        from tests.test_extraction import SYLLABUS_FACTS, make_responder

        set_router(ModelRouter(FakeLLMClient(make_responder(SYLLABUS_FACTS))))
        _ingest(db, client, "tests/fixtures/ml_syllabus.md")
        # ASK questions run against the narrating responder.
        set_router(ModelRouter(FakeLLMClient(_synth_responder())))
        yield client
    stage.llm_available = original
    set_router(ModelRouter(FakeLLMClient(_synth_responder())))


def _synth_responder():
    def respond(agent, purpose, user_prompt):
        if purpose == "classify":
            return {
                "doc_kind": "syllabus",
                "title": "Machine Learning CS301",
                "topic": "Machine Learning",
                "importance": 0.8,
                "summary": "Syllabus.",
            }
        if purpose == "reasoning":
            return {"answer": "Based on your syllabus, Assignment 4 is due October 13."}
        return {"dates": [], "tasks": [], "commitments": [], "entities": [], "relations": []}

    return respond


def _ingest(db, client, path):
    from app.workers.handlers import HANDLERS
    from app.workers.queue import claim_next

    with open(path, "rb") as fh:
        response = client.post(
            "/inbox/upload", files=[("files", (path.split("/")[-1], fh, "text/markdown"))]
        )
    assert response.status_code == 201
    while True:
        job = claim_next(db)
        if job is None:
            break
        HANDLERS[job.type](db, job)
        db.commit()


def test_intent_routing():
    assert classify_intent("What deadlines am I forgetting?") == "deadlines"
    assert classify_intent("things due next week") == "deadlines"
    assert classify_intent("Show every commitment I made to John") == "commitments"
    assert classify_intent("What am I behind on?") == "behind"
    assert classify_intent("Find everything about convolutional networks") == "retrieval"


def test_search_finds_syllabus_with_signals(ask_client):
    results = ask_client.get("/search", params={"q": "assignment deadline October"}).json()
    assert len(results) >= 1
    assert (
        top_matches := [
            r for r in results[:3] if "October" in r["text"] or "Assignment" in r["text"]
        ]
    ), results[:2]
    assert top_matches[0]["matched_signals"]  # explainability: which signals matched


def test_search_empty_index(ask_client, db):
    # New user with no documents gets empty results, not an error.
    with TestClient(app) as client:
        client.post(
            "/auth/register",
            json={"email": "empty@test.dev", "password": "password-123", "display_name": "E"},
        )
        results = client.get("/search", params={"q": "anything"}).json()
        assert results == []


def test_ask_deadlines_uses_structured_path(ask_client):
    response = ask_client.post("/ask", json={"question": "What's due this semester?"})
    assert response.status_code == 200
    body = response.json()
    assert body["path"] == "deadlines"
    assert body["facts"]["deadlines"], "confirmed deadlines must come from structured rows"
    titles = [d["title"] for d in body["facts"]["deadlines"]]
    assert "Assignment 4" in titles
    # Citations reference the source document with the raw quote.
    assert any(c.document_id for c in map(_citation, body["citations"]))


def test_specific_deadline_question_is_not_limited_to_next_week(ask_client):
    response = ask_client.post("/ask", json={"question": "When is Assignment 4 due?"})
    deadlines = response.json()["facts"]["deadlines"]
    assert any(deadline["title"] == "Assignment 4" for deadline in deadlines)


def _citation(raw: dict):
    from app.agents.ask_agent import Citation

    return Citation(**raw)


def test_ask_semantic_query_uses_retrieval_path(ask_client):
    response = ask_client.post(
        "/ask", json={"question": "What do the lectures say about neural networks?"}
    )
    body = response.json()
    assert body["path"] == "retrieval"
    assert body["answer"]


def test_ask_requires_auth(db):
    with TestClient(app) as client:
        assert client.post("/ask", json={"question": "hello"}).status_code == 401
