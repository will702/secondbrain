"""PMAX bridge: shells out to the `pmax` Go binary (argv only, never a shell).

PMAX owns every file move/delete. This module can only ask it to decide ONE
staged row at a time (approve-one / reject-one); there is no bulk call.
"""

import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings

_PLAN_RE = re.compile(r"^plan-[A-Za-z0-9._-]+\.tsv$")
_ROW_RE = re.compile(r"^[0-9a-f]{16}$")
_TIMEOUT_S = 15


class PmaxUnavailable(Exception):
    pass


class PmaxRejected(Exception):
    """pmax refused the request (stale id, stage-only, vanished source...)."""


def pmax_bin() -> str | None:
    configured = getattr(get_settings(), "pmax_bin", None)
    for cand in (configured, shutil.which("pmax"), str(Path.home() / ".local/bin/pmax")):
        if cand and Path(cand).is_file():
            return cand
    return None


def _run(args: list[str]) -> subprocess.CompletedProcess:
    binary = pmax_bin()
    if binary is None:
        raise PmaxUnavailable("pmax binary not found")
    try:
        return subprocess.run(  # noqa: S603 — argv list, validated inputs
            [binary, *args], capture_output=True, text=True, timeout=_TIMEOUT_S, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PmaxUnavailable(str(exc)) from exc


def _json(args: list[str]) -> dict:
    proc = _run(args)
    if proc.returncode != 0:
        raise PmaxUnavailable(proc.stderr.strip() or f"pmax exited {proc.returncode}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise PmaxUnavailable("pmax returned invalid JSON") from exc


def status() -> dict:
    """Never raises: the system dashboard must render with PMAX missing."""
    try:
        return {"available": True, **_json(["status", "--json"])}
    except PmaxUnavailable as exc:
        return {"available": False, "error": str(exc)}


def pending() -> dict:
    return _json(["pending", "--json"])


def decide_row(plan: str, row_id: str, approve: bool) -> None:
    """Decide exactly one staged row. Inputs are validated before reaching argv."""
    if not _PLAN_RE.match(plan) or not _ROW_RE.match(row_id):
        raise PmaxRejected("invalid plan or row id")
    proc = _run(["approve-one" if approve else "reject-one", plan, row_id])
    if proc.returncode != 0:
        raise PmaxRejected(proc.stderr.strip() or "pmax refused the request")


def state_dir() -> Path:
    return Path(os.environ.get("PMAX_STATE") or Path.home() / ".local/state/pmax")


def write_load_snapshot(load: dict) -> bool:
    """Tell PMAX how busy the next 24h are, so it can go easy on you.

    Best effort and atomic. Only writes if PMAX's state dir already exists (PMAX is
    installed); PMAX ignores the file once it is >12h old, so a stale snapshot is harmless.
    """
    directory = state_dir()
    if not directory.is_dir():
        return False
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "level": load["today"]["level"],
        "today_booked_pct": load["today"]["booked_pct"],
        "week_level": load["week"]["level"],
    }
    tmp = directory / "load.json.tmp"
    try:
        tmp.write_text(json.dumps(payload))
        os.replace(tmp, directory / "load.json")
    except OSError:
        return False
    return True
