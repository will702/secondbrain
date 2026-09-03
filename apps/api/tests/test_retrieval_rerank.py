"""Unit tests: local-ai embedding provider, reranker client, and the rerank
stage in hybrid retrieval. All offline (patched httpx / fake providers);
live behaviour is covered by evals (make eval).
"""

import uuid
from datetime import datetime, timezone

import httpx
import pytest

from app.agents import reranker as reranker_mod
from app.agents.embeddings import FakeEmbedProvider, LocalAIEmbedProvider


def _patch_post(monkeypatch, responder):
    """Patch httpx.post; responder(url, payload) -> httpx.Response."""
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append(json)
        return responder(url, json)

    monkeypatch.setattr(httpx, "post", fake_post)
    return calls


def _json_response(url: str, payload: dict) -> httpx.Response:
    # raise_for_status() needs a bound request
    return httpx.Response(200, json=payload, request=httpx.Request("POST", url))


# --- LocalAIEmbedProvider ---------------------------------------------------


def test_localai_provider_documents_and_query_mode(monkeypatch):
    dim = 1024

    def responder(url, payload):
        assert url.endswith("/v1/embeddings")
        n = len(payload["input"])
        return _json_response(url, {"data": [
            {"object": "embedding", "index": i, "embedding": [0.01] * dim}
            for i in range(n)]})

    calls = _patch_post(monkeypatch, responder)
    provider = LocalAIEmbedProvider(base_url="http://localtest/v1")

    vectors = provider.embed_texts(["a", "b", "c"])
    assert len(vectors) == 3 and len(vectors[0]) == dim
    assert calls[-1] == {"input": ["a", "b", "c"]}

    query_vec = provider.embed_query("when is the deadline")
    assert len(query_vec) == dim
    assert calls[-1] == {"input": "when is the deadline", "query": True}


def test_localai_provider_dim_guard(monkeypatch):
    def responder(url, payload):
        return _json_response(url, {"data": [
            {"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]}]})

    _patch_post(monkeypatch, responder)
    provider = LocalAIEmbedProvider(base_url="http://localtest/v1")
    with pytest.raises(RuntimeError, match="schema"):
        provider.embed_texts(["x"])


def test_fake_provider_dim_follows_settings():
    embedder = FakeEmbedProvider()
    assert len(embedder.embed_texts(["hello"])[0]) == embedder.dim


# --- reranker client ---------------------------------------------------------


def test_reranker_disabled_returns_none(monkeypatch):
    monkeypatch.setenv("RERANKER_ENABLED", "false")
    from app.core.config import get_settings
    get_settings.cache_clear()
    try:
        assert reranker_mod.rerank("q", ["a"]) is None
    finally:
        monkeypatch.delenv("RERANKER_ENABLED")
        get_settings.cache_clear()


def test_reranker_unreachable_returns_none(monkeypatch):
    def boom(url, json=None, timeout=None):
        raise httpx.ConnectError("server down")

    monkeypatch.setattr(httpx, "post", boom)
    reranker_mod.reset_breaker()
    scores = reranker_mod.rerank("q", ["a", "b"])
    assert scores is None
    # circuit breaker: immediate second call also skips the network
    assert reranker_mod.rerank_with_breaker("q", ["a", "b"]) is None


def test_reranker_maps_scores_by_index(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("RERANKER_ENABLED", "true")
    get_settings.cache_clear()

    def responder(url, payload):
        assert url.endswith("/v1/rerank")
        return _json_response(url, {"results": [
            {"index": 1, "relevance_score": 0.01},
            {"index": 0, "relevance_score": 0.9},
        ]})

    _patch_post(monkeypatch, responder)
    reranker_mod.reset_breaker()
    assert reranker_mod.rerank("q", ["relevant", "filler"]) == [0.9, 0.01]


# --- hybrid retrieval rerank stage -------------------------------------------


@pytest.fixture()
def three_chunks(db):
    from app.models import Document, DocumentChunk, User
    from app.models.enums import DocumentStatus

    user = User(email="rerank-test@example.com", password_hash="x", display_name="T")
    db.add(user)
    db.flush()
    doc = Document(user_id=user.id, sha256="0" * 64, original_filename="syl.pdf",
                   storage_path="data/syl.pdf", mime_type="application/pdf",
                   title="Syllabus", status=DocumentStatus.processed)
    db.add(doc)
    db.flush()
    embedder = FakeEmbedProvider()
    for index, (section, text) in enumerate((
        ("filler", "Zebras graze on the savannah among unrelated topics."),
        ("logistics", "Course logistics: rooms, offices, and email policies."),
        ("hit", "The final exam is on December 12 at 09:00 in Hall B."),
    )):
        db.add(DocumentChunk(
            user_id=user.id, document_id=doc.id, text=text, section=section,
            chunk_index=index, token_count=len(text) // 4,
            embedding=embedder.embed_texts([text])[0],
        ))
    db.commit()
    return db, user.id


def test_rerank_promotes_relevant_chunk(db, three_chunks, fake_embeddings, monkeypatch):
    from app.services.retrieval.hybrid import search_chunks

    _, user_id = three_chunks

    def fake_rerank(query, chunks, **kw):
        return [0.95 if "final exam" in c else 0.05 for c in chunks]

    monkeypatch.setattr(reranker_mod, "rerank_with_breaker", fake_rerank)
    results = search_chunks(db, user_id, "when is the final exam", limit=3)
    assert results, "no results"
    assert results[0]["section"] == "hit"
    assert results[0]["rerank_score"] == 0.95
    assert "rerank" in results[0]["matched_signals"]


def test_search_without_reranker_keeps_fused_order(db, three_chunks, fake_embeddings, monkeypatch):
    from app.services.retrieval.hybrid import search_chunks

    _, user_id = three_chunks
    monkeypatch.setattr(reranker_mod, "rerank_with_breaker", lambda q, c: None)
    results = search_chunks(db, user_id, "final exam december", limit=3)
    assert results
    assert all("rerank_score" not in r for r in results)


def test_search_empty_corpus_returns_empty(db, fake_embeddings, monkeypatch):
    from app.services.retrieval.hybrid import search_chunks

    random_user = uuid.uuid4()
    assert search_chunks(db, random_user, "anything", limit=3) == []
