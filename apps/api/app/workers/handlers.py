"""Job handler registry: job.type → handler(db, job)."""

import logging

from sqlalchemy.orm import Session as OrmSession

from app.models import Job, User
from app.services.ingestion.pipeline import ingest_document
from app.workers.queue import enqueue

logger = logging.getLogger("secondbrain.workers")


def handle_ingest_document(db: OrmSession, job: Job) -> None:
    document_id = job.payload["document_id"]
    ingest_document(db, document_id)
    enqueue(
        db,
        "plan.recompute",
        {"reason": "document_processed", "document_id": document_id},
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
