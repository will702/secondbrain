import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.agents.embeddings import FakeEmbedProvider, set_embedder
from app.main import app
from app.models import (
    ActionProposal,
    AuditLog,
    Deadline,
    Document,
    Entity,
    Event,
    Job,
    Project,
    ReviewItem,
    Task,
    User,
)
from app.models.enums import EntityKind, EventKind
from app.services.ingestion.lineage import record_derivation
from app.services.proposals.service import propose
from app.workers.handlers import HANDLERS
from app.workers.queue import claim_next

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
        assert row.embedding is not None and len(row.embedding) == 1024


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
            response = client.post("/inbox/upload", files=[("files", ("a.csv", fh, "text/csv"))])
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
        document_id = _upload(client, FIXTURES / "assignment4.txt").json()[0]["document_id"]
        _drain_jobs(db)
    with TestClient(app) as other:
        other.post(
            "/auth/register",
            json={"email": "other@test.dev", "password": "password-123", "display_name": "O"},
        )
        assert other.get("/documents").json() == []
        assert other.delete(f"/documents/{document_id}").status_code == 404


def test_document_delete_retracts_exclusive_facts_and_keeps_shared_ones(db):
    with TestClient(app) as client:
        _registered_client(client)
        first_id = _upload(client, FIXTURES / "ml_syllabus.md").json()[0]["document_id"]
        second_id = _upload(client, FIXTURES / "assignment4.txt").json()[0]["document_id"]
        first = db.get(Document, uuid.UUID(first_id))
        second = db.get(Document, uuid.UUID(second_id))
        user_id = first.user_id

        entity = Entity(
            user_id=user_id,
            kind=EntityKind.project,
            name="Shared project",
            normalized_name="shared project",
            aliases=[],
            confidence=0.9,
        )
        db.add(entity)
        db.flush()
        project = Project(
            user_id=user_id, entity_id=entity.id, name="Shared project", kind="project"
        )
        db.add(project)
        db.flush()
        first.project_id = project.id
        second.project_id = project.id

        shared_task = Task(user_id=user_id, project_id=project.id, title="Shared task")
        exclusive_task = Task(user_id=user_id, project_id=project.id, title="Exclusive task")
        deadline = Deadline(
            user_id=user_id,
            project_id=project.id,
            title="Exclusive deadline",
            normalized_at=None,
            date_is_exact=False,
            raw_expression="later",
            timezone="Asia/Jakarta",
            confidence=0.4,
            explicit=False,
            status="tentative",
            provenance={"document_id": first_id},
        )
        review = ReviewItem(
            user_id=user_id,
            kind="deadline",
            question="When?",
            payload={},
            provenance={"document_id": first_id},
        )
        db.add_all([shared_task, exclusive_task, deadline, review])
        db.flush()
        event = Event(
            user_id=user_id,
            kind=EventKind.focus,
            title="Focus: Exclusive task",
            starts_at=first.created_at,
            ends_at=first.created_at + timedelta(hours=1),
            timezone="Asia/Jakarta",
            provider="local",
            editable=True,
            task_id=exclusive_task.id,
        )
        db.add(event)
        propose(
            db,
            db.get(User, user_id),
            "create_event",
            {
                "title": "Focus: Exclusive task",
                "starts_at": first.created_at.isoformat(),
                "ends_at": (first.created_at + timedelta(hours=1)).isoformat(),
                "task_id": str(exclusive_task.id),
            },
            reason="Schedule exclusive task",
            proposed_by="planning",
            evidence={"task_id": str(exclusive_task.id)},
        )
        for document in (first, second):
            provenance = {"document_id": str(document.id)}
            record_derivation(db, document.id, "entity", entity.id, provenance)
            record_derivation(db, document.id, "project", project.id, provenance)
            record_derivation(db, document.id, "task", shared_task.id, provenance)
        provenance = {"document_id": first_id}
        record_derivation(db, first.id, "task", exclusive_task.id, provenance)
        record_derivation(db, first.id, "deadline", deadline.id, provenance)
        record_derivation(db, first.id, "review", review.id, provenance)
        db.commit()

        exclusive_task_id = exclusive_task.id
        shared_task_id = shared_task.id
        event_id = event.id
        deadline_id = deadline.id
        review_id = review.id
        project_id = project.id
        entity_id = entity.id
        first_path = Path(first.storage_path)
        assert first_path.exists()
        response = client.delete(f"/documents/{first_id}")
        assert response.status_code == 204
        db.expire_all()
        assert db.get(Document, first_id) is None
        assert not first_path.exists()
        assert db.get(Task, exclusive_task_id) is None
        assert db.get(Event, event_id) is None
        assert db.get(Deadline, deadline_id) is None
        assert db.get(ReviewItem, review_id) is None
        assert db.query(ActionProposal).count() == 0
        assert db.get(Task, shared_task_id) is not None
        assert db.get(Project, project_id) is not None
        assert db.get(Entity, entity_id) is not None
        assert (
            db.query(AuditLog).filter_by(action="document.delete", object_id=first_id).count() == 1
        )

        queued = db.query(Job).filter(Job.payload["document_id"].as_string() == first_id).first()
        assert queued is not None
        HANDLERS["ingest_document"](db, queued)

        assert client.delete(f"/documents/{second_id}").status_code == 204
        db.expire_all()
        assert db.get(Task, shared_task_id) is None
        assert db.get(Project, project_id) is None
        assert db.get(Entity, entity_id) is None
