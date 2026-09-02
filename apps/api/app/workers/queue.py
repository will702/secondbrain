"""Postgres-backed durable job queue.

Claim semantics: single UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED)
so N worker processes can claim concurrently without double-processing.
Idempotency: unique idempotency_key dedupes enqueues; handlers must also be
idempotent (natural-key writes) to survive at-least-once redelivery.
"""

import json
import logging
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session as OrmSession

from app.models import Job
from app.models.enums import JobStatus

logger = logging.getLogger("secondbrain.queue")

BACKOFF_BASE_SECONDS = 30


def enqueue(
    db: OrmSession,
    job_type: str,
    payload: dict,
    user_id=None,
    idempotency_key: str | None = None,
    run_at: datetime | None = None,
    max_attempts: int = 3,
) -> Job:
    job = Job(
        user_id=user_id,
        type=job_type,
        payload=payload,
        idempotency_key=idempotency_key,
        run_at=run_at or datetime.now(UTC),
        max_attempts=max_attempts,
    )
    db.add(job)
    try:
        db.flush()
    except sa.exc.IntegrityError:
        # Idempotency key already enqueued — return the existing job.
        db.rollback()
        existing = db.execute(
            sa.select(Job).where(Job.idempotency_key == idempotency_key)
        ).scalar_one()
        return existing
    return job


def claim_next(db: OrmSession) -> Job | None:
    statement = (
        sa.update(Job)
        .where(
            Job.id
            == sa.select(Job.id)
            .where(Job.status == JobStatus.pending, Job.run_at <= datetime.now(UTC))
            .order_by(Job.run_at)
            .limit(1)
            .scalar_subquery()
        )
        .values(status=JobStatus.claimed, claimed_at=datetime.now(UTC), attempts=Job.attempts + 1)
        .returning(Job)
    )
    result = db.execute(statement)
    row = result.scalar_one_or_none()
    if row is not None:
        db.commit()
    return row


def complete(db: OrmSession, job: Job) -> None:
    job.status = JobStatus.done
    db.commit()


def fail(db: OrmSession, job: Job, error: str) -> None:
    job.last_error = error[:2000]
    if job.attempts >= job.max_attempts:
        job.status = JobStatus.dead
        logger.error(
            "job %s died after %d attempts",
            job.type,
            job.attempts,
            extra={"job_id": job.id, "data": {"error": error[:500]}},
        )
    else:
        job.status = JobStatus.pending
        job.run_at = datetime.now(UTC) + timedelta(
            seconds=BACKOFF_BASE_SECONDS * (2 ** (job.attempts - 1))
        )
    db.commit()


def payload_str(payload: dict) -> str:
    return json.dumps(payload, default=str)[:500]
