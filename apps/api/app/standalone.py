"""Standalone runtime for the packaged app: one process = database bootstrap
→ migrations → API + static web + background workers.

Usage (the desktop launcher sets env; defaults suit local testing):
    uv run python -m app.standalone [--host 127.0.0.1] [--port 8000]

Env of note (all optional):
    PORT / --port      API listen port (default 8000)
    WEB_DIST_DIR       static web export served at "/" (same-origin UI)
    DATABASE_URL       target database (created if missing)
    SECONDBRAIN_MANAGE_DB=1 + SECONDBRAIN_POSTGRES_BIN/_PGDATA/_PG_LOG
                      embedded postgres lifecycle (see app.dblocal)

Progress is reported as JSON lines on stdout ({"event": "stage", ...}) for the
desktop launcher's startup UI; logs go to stderr.
"""

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

import psycopg
import sqlalchemy.engine

from app.core.config import get_settings
from app.core.logging import configure_logging

# Stdout carries only JSON stage events for the desktop launcher; logs → stderr.
configure_logging(sys.stderr)
logger = logging.getLogger("secondbrain.standalone")


def _emit(stage: str, status: str, **extra: object) -> None:
    print(json.dumps({"event": "stage", "stage": stage, "status": status, **extra}), flush=True)


def _bundle_root() -> Path:
    """apps/api in dev; the PyInstaller bundle root when frozen."""
    if getattr(sys, "frozen", False):  # pragma: no cover - packaging only
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]


def _ensure_database(connect_timeout_s: float = 30.0) -> None:
    """Create the target database if it doesn't exist yet (fresh install)."""
    url = sqlalchemy.engine.make_url(get_settings().database_url)
    if url.get_backend_name() != "postgresql":  # pragma: no cover - non-postgres deployments
        return
    admin_url = url.set(drivername="postgresql", database="postgres")

    deadline = time.monotonic() + connect_timeout_s
    while True:
        try:
            with psycopg.connect(
                admin_url.render_as_string(hide_password=False), autocommit=True
            ) as conn:
                exists = conn.execute(
                    "SELECT 1 FROM pg_database WHERE datname = %s", (url.database,)
                ).fetchone()
                if not exists:
                    logger.info("creating database %s", url.database)
                    conn.execute(f'CREATE DATABASE "{url.database}"')
            return
        except psycopg.OperationalError as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"postgres unreachable after {connect_timeout_s}s: {exc}") from exc
            logger.warning("postgres not ready yet (%s); retrying", exc.__class__.__name__)
            time.sleep(1.0)


def _run_migrations() -> None:
    from alembic.config import Config

    from alembic import command

    root = _bundle_root()
    ini = root / "alembic.ini"
    cfg = Config(str(ini)) if ini.exists() else Config()
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.attributes["skip_logging_config"] = True
    logger.info("applying migrations")
    command.upgrade(cfg, "head")


def _start_workers(stop: threading.Event, count: int = 1) -> list[threading.Thread]:
    from app.workers import runner

    def loop() -> None:
        while not stop.is_set():
            try:
                worked = runner.process_one()
            except Exception:
                logger.exception("worker loop iteration failed")
                worked = False
            if not worked:
                stop.wait(runner.POLL)

    threads = []
    for i in range(count):
        t = threading.Thread(target=loop, name=f"worker-{i}", daemon=True)
        t.start()
        threads.append(t)
    logger.info("worker threads started (%d)", count)
    return threads


def main() -> int:
    parser = argparse.ArgumentParser(prog="secondbrain-standalone")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    args = parser.parse_args()

    from app.dblocal import maybe_start_local_postgres

    db = None
    try:
        if os.environ.get("SECONDBRAIN_MANAGE_DB") == "1":
            _emit("database", "starting")
            db = maybe_start_local_postgres()
            assert db is not None  # manage-db mode always returns a supervisor
            _emit("database", "ready", port=db.port)

        _ensure_database()
        _emit("migrations", "running")
        _run_migrations()
        _emit("migrations", "done")

        import uvicorn

        from app.main import app

        server = uvicorn.Server(
            # Explicit loop/protocol: the "auto" variants dynamically import
            # uvloop/httptools, which is fragile inside a frozen bundle.
            uvicorn.Config(
                app,
                host=args.host,
                port=args.port,
                access_log=False,
                loop="asyncio",
                http="h11",
            )
        )

        stop = threading.Event()
        _start_workers(stop)
        _emit("api", "starting", port=args.port)

        def _shutdown(signum: int, frame: object) -> None:
            logger.info("signal %d received — shutting down", signum)
            stop.set()
            server.should_exit = True

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

        api_thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
        api_thread.start()

        deadline = time.monotonic() + 30
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        if not server.started:
            logger.error("API failed to start on %s:%s", args.host, args.port)
            stop.set()
            return 1
        _emit("api", "ready", port=args.port)

        while api_thread.is_alive():
            api_thread.join(timeout=1.0)
        stop.set()
        logger.info("standalone runtime stopped")
        return 0
    finally:
        _emit("shutdown", "started")
        if db is not None:
            db.stop()
        _emit("shutdown", "done")


if __name__ == "__main__":
    sys.exit(main())
