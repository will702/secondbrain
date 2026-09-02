from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.embeddings import FakeEmbedProvider, set_embedder
from app.main import app
from app.models import Document
from app.models.enums import DocumentStatus
from app.workers.queue import claim_next
from app.workers.handlers import HANDLERS

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def fake_embeddings():
    set_embedder(FakeEmbedProvider())
    yield
    set_embedder(FakeEmbedProvider())  # keep tests hermetic


def _registered_client(client: TestClient) -> TestClient:
    response = client.post(
        "/auth/register",
        json={"email": "ingest@test.dev", "password": "password-123", "display_name": "Ingest"},
    )
    assert response.status_code == 201
    return client


def _drain_jobs(db) -> None:
    """Run queued jobs synchronously (mirrors worker dispatch without a subprocess)."""
    while True:
        job = claim_next(db)
        if job is None:
            break
        HANDLERS[job.type](db, job)
        db.commit()


def _upload(client: TestClient, path: Path):
    with open(path, "rb") as fh:
        return client.post(
            "/inbox/upload",
            files=[("files", (path.name, fh, "application/octet-stream"))],
        )


def test_upload_then_ingest_processes_document(db):
    with TestClient(app) as client:
        _registered_client(client)
        response = _upload(client, FIXTURES / "ml_syllabus.md")
        assert response.status_code == 201
        body = response.json()
        assert body[0]["duplicate"] is False
        document_id = body[0]["document_id"]

        _drain_jobs(db)

        detail = client.get(f"/documents/{document_id}").json()
        assert detail["status"] == "processed", detail
        assert detail["doc_kind"] in ("syllabus", "other")  # classification lands in M2
        assert detail["chunk_count"] >= 1

        chunks = client.get(f"/documents/{document_id}/chunks").json()
        assert all(len(c["text"]) > 0 for c in chunks)
        full_text = "\n".join(c["text"] for c in chunks)
        assert "October 13" in full_text  # deadline text survived the pipeline

        # Vectors present with correct dimensionality.
        from app.models import DocumentChunk

        row = db.query(DocumentChunk).filter_by(document_id=document_id).first()
        assert row.embedding is not None and len(row.embedding) == 384


def test_duplicate_upload_is_noop(db):
    with TestClient(app) as client:
        _registered_client(client)
        first = _upload(client, FIXTURES / "schedule.csv").json()
        second = _upload(client, FIXTURES / "schedule.csv").json()
        assert second[0]["duplicate"] is True
        assert second[0]["document_id"] == first[0]["document_id"]
        assert db.query(Document).count() == 1


def test_unsupported_extension_rejected(db):
    with TestClient(app) as client:
        _registered_client(client)
        response = client.post(
            "/inbox/upload",
            files=[("files", ("evil.exe", b"MZ...", "application/octet-stream"))],
        )
        assert response.status_code == 415


def test_requires_auth(db):
    with TestClient(app) as client:
        assert client.get("/documents").status_code == 401
        with open(FIXTURES / "schedule.csv", "rb") as fh:
            response = client.post(
                "/inbox/upload", files=[("files", ("a.csv", fh, "text/csv"))]
            )
        assert response.status_code == 401


def test_failed_parse_marks_document_failed(db):
    with TestClient(app) as client:
        _registered_client(client)
        # Valid extension, garbage content → parser raises, document failed, job dies.
        response = client.post(
            "/inbox/upload",
            files=[("files", ("broken.pdf", b"not a pdf", "application/pdf"))],
        )
        assert response.status_code == 201
        _drain_jobs(db)
        document_id = response.json()[0]["document_id"]
        detail = client.get(f"/documents/{document_id}").json()
        assert detail["status"] == "failed"
        assert detail["error"]


def test_user_isolation(db):
    with TestClient(app) as client:
        _registered_client(client)
        _upload(client, FIXTURES / "assignment4.txt")
        _drain_jobs(db)
    with TestClient(app) as other:
        other.post(
            "/auth/register",
            json={"email": "other@test.dev", "password": "password-123", "display_name": "O"},
        )
        assert other.get("/documents").json() == []
