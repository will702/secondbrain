"""Worker loop: claim jobs from the Postgres queue and dispatch to handlers.

Run standalone: uv run python -m app.workers.runner
Multiple runners are safe (SKIP LOCKED claiming).
"""

import logging
import signal
import sys
import time

from app.core.db import SessionLocal
from app.core.logging import configure_logging
from app.workers.handlers import HANDLERS
from app.workers.queue import claim_next, complete, fail

configure_logging()
logger = logging.getLogger("secondbrain.runner")

from app.core.config import get_settings  # noqa: E402

POLL = get_settings().worker_poll_interval_seconds
_running = True


def _stop(signum, frame) -> None:
    global _running
    _running = False
    logger.info("signal %d received — draining", signum)


def process_one() -> bool:
    db = SessionLocal()
    try:
        job = claim_next(db)
        if job is None:
            return False
        handler = HANDLERS.get(job.type)
        logger.info(
            "job %s attempt %d", job.type, job.attempts, extra={"job_id": job.id}
        )
        try:
            if handler is None:
                logger.error("no handler for job type %r", job.type)
                fail(db, job, f"no handler for {job.type}")
            else:
                handler(db, job)
                complete(db, job)
        except Exception as exc:
            db.rollback()
            fail(db, job, f"{type(exc).__name__}: {exc}")
            logger.exception("job %s failed", job.type, extra={"job_id": job.id})
        return True
    finally:
        db.close()


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    logger.info("worker runner started (poll=%.1fs)", POLL)
    while _running:
        try:
            worked = process_one()
        except Exception:
            logger.exception("worker loop iteration failed")
            worked = False
        if not worked:
            time.sleep(POLL)
    logger.info("worker runner stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
