"""Job handler registry: job.type → handler(db, job)."""

import logging
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session as OrmSession

from app.models import Document, Job, User
from app.services.ingestion.pipeline import ingest_document
from app.workers.queue import enqueue

logger = logging.getLogger("secondbrain.workers")


def handle_ingest_document(db: OrmSession, job: Job) -> None:
    document_id = uuid.UUID(job.payload["document_id"])
    db.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtext(:document_id))"),
        {"document_id": str(document_id)},
    )
    if db.get(Document, document_id) is None:
        return
    try:
        ingest_document(db, document_id)
    except Exception as exc:
        from app.models.enums import DocumentStatus

        doc = db.get(Document, document_id)
        if doc is not None and doc.status != DocumentStatus.processed:
            doc.status = DocumentStatus.failed
            doc.error = f"{type(exc).__name__}: {exc}"
            db.commit()
        raise

    enqueue(
        db,
        "plan.recompute",
        {"reason": "document_processed", "document_id": str(document_id)},
        user_id=job.user_id,
        idempotency_key=f"plan-recompute-doc-{document_id}-{_today_key()}",
    )


def _today_key() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y%m%d")


def handle_plan_recompute(db: OrmSession, job: Job) -> None:
    if job.user_id is None:
        return
    from app.services.scheduling.service import recompute_plan

    user = db.get(User, job.user_id)
    if user is None:
        return
    # Background recomputation respects autonomy: level >= 2 (Planner) may
    # rewrite soft blocks; level 1 computes and records the plan without
    # touching the calendar (user applies it from the Calendar surface).
    recompute_plan(db, user, apply=user.autonomy_level >= 2)


HANDLERS = {
    "ingest_document": handle_ingest_document,
    "plan.recompute": handle_plan_recompute,
}
