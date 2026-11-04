"""Embedded PostgreSQL lifecycle for the packaged app (manage-db mode).

The desktop launcher sets SECONDBRAIN_MANAGE_DB=1 plus the binary and data
directories; this module then owns port selection, first-run initdb, server
start/stop, and the DATABASE_URL handed to the rest of the app.

Env contract (set by the launcher before the backend starts):
    SECONDBRAIN_MANAGE_DB=1              enable embedded mode
    SECONDBRAIN_POSTGRES_BIN=<dir>       staged postgres/ tree (bin/, lib/, share/)
    SECONDBRAIN_PGDATA=<dir>             cluster directory (initdb'd on first run)
    SECONDBRAIN_PG_LOG=<file>            optional server log (stderr inherits otherwise)
"""

import logging
import os
import signal
import socket
import subprocess
import time
from pathlib import Path

import psycopg

logger = logging.getLogger("secondbrain.dblocal")

USER = "secondbrain"
DATABASE = "secondbrain"


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class LocalPostgres:
    """Supervises a postgres server process bound to 127.0.0.1 on a free port."""

    def __init__(self, bin_dir: Path, data_dir: Path, log_file: Path | None = None):
        self.bin_dir = bin_dir
        self.data_dir = data_dir
        self.log_file = log_file
        self.port = pick_free_port()
        self.proc: subprocess.Popen | None = None

    @property
    def url(self) -> str:
        return f"postgresql+psycopg://{USER}@127.0.0.1:{self.port}/{DATABASE}"

    def initdb(self) -> None:
        if (self.data_dir / "PG_VERSION").exists():
            return
        logger.info("initializing database cluster at %s", self.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                str(self.bin_dir / "initdb"),
                "-D", str(self.data_dir),
                "--username", USER,
                "--auth-local", "trust",
                "--auth-host", "trust",
                "--no-locale",
                "-E", "UTF8",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"initdb failed:\n{result.stderr[-2000:]}")

    def _clear_stale_pid(self) -> None:
        pid_file = self.data_dir / "postmaster.pid"
        if not pid_file.exists():
            return
        try:
            pid = int(pid_file.read_text().splitlines()[0])
        except (ValueError, IndexError):
            pid = -1
        if pid <= 0 or not _pid_alive(pid):
            logger.info("removing stale postmaster.pid (pid=%s)", pid)
            pid_file.unlink(missing_ok=True)

    def _admin_dsn(self) -> str:
        return f"host=127.0.0.1 port={self.port} user={USER} dbname=postgres connect_timeout=2"

    def _readiness_error(self) -> str | None:
        """Poll until the server accepts connections; None on success."""
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                return f"postgres exited with code {self.proc.returncode}"
            try:
                psycopg.connect(self._admin_dsn()).close()
                return None
            except psycopg.OperationalError:
                time.sleep(0.3)
        return "timed out waiting for postgres readiness"

    def start(self) -> None:
        self.initdb()
        self._clear_stale_pid()
        logger.info("starting embedded postgres on 127.0.0.1:%d", self.port)
        log = (
            open(self.log_file, "ab")
            if self.log_file is not None
            else subprocess.DEVNULL
        )
        try:
            self.proc = subprocess.Popen(
                [
                    str(self.bin_dir / "postgres"),
                    "-D", str(self.data_dir),
                    "-c", "listen_addresses=127.0.0.1",
                    "-c", f"port={self.port}",
                    "-c", f"unix_socket_directories={self.data_dir}",
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                close_fds=True,
            )
        finally:
            if self.log_file is not None:
                log.close()
        error = self._readiness_error()
        if error is not None:
            raise RuntimeError(f"{error} (log: {self.log_file or 'stderr'})")

    def stop(self, timeout_s: float = 20.0) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            logger.info("stopping embedded postgres (fast shutdown)")
            try:
                # SIGINT = "fast" shutdown: finishes in-flight queries, no new ones.
                self.proc.send_signal(signal.SIGINT)
                self.proc.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                logger.warning("postgres did not stop within %.0fs; killing", timeout_s)
                self.proc.kill()
                self.proc.wait(timeout=5)
        self.proc = None


def maybe_start_local_postgres() -> LocalPostgres | None:
    """Entry point used by app.standalone: start the embedded server when the
    launcher asked for it, and export DATABASE_URL for the rest of the app."""
    if os.environ.get("SECONDBRAIN_MANAGE_DB") != "1":
        return None
    log_env = os.environ.get("SECONDBRAIN_PG_LOG")
    db = LocalPostgres(
        bin_dir=Path(os.environ["SECONDBRAIN_POSTGRES_BIN"]),
        data_dir=Path(os.environ["SECONDBRAIN_PGDATA"]),
        log_file=Path(log_env) if log_env else None,
    )
    db.start()
    os.environ["DATABASE_URL"] = db.url
    return db
