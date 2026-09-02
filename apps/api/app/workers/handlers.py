"""Job handler registry: job.type → handler(db, job)."""

import logging

from sqlalchemy.orm import Session as OrmSession

from app.models import Job
from app.services.ingestion.pipeline import ingest_document
from app.workers.queue import enqueue

logger = logging.getLogger("secondbrain.workers")


def handle_ingest_document(db: OrmSession, job: Job) -> None:
    document_id = job.payload["document_id"]
    ingest_document(db, document_id)
    # After understanding a document, recompute affected plans (M4 wires the planner;
    # the trigger is durable from day one so nothing gets lost before then).
    enqueue(
        db,
        "plan.recompute",
        {"reason": "document_processed", "document_id": document_id},
        user_id=job.user_id,
        idempotency_key=f"plan-recompute-doc-{document_id}",
    )


def handle_noop(db: OrmSession, job: Job) -> None:
    """Handlers not yet implemented keep their jobs alive instead of dying loudly."""
    logger.info("job type %r has no handler yet; completing as no-op", job.type)


HANDLERS = {
    "ingest_document": handle_ingest_document,
    "plan.recompute": handle_noop,  # replaced by the planner in M4
}
