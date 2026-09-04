"""Guided AI setup for the packaged app: install the local-ai runtime,
download models, and supervise the server — all inside the app's own
application-support directory.

Launcher contract (set by the desktop shell; absent in dev):
    SECONDBRAIN_AI_DIR=<app support>/ai          runtime home (venv, config, models)
    SECONDBRAIN_UV_BIN=<resources>/uv/uv         bundled uv binary
    SECONDBRAIN_LOCALAI_WHEEL=<resources>/…whl   localai wheel
    SECONDBRAIN_LOCALAI_CONFIG=<resources>/…yaml config template (model manifest)

The AI server binds a fixed 127.0.0.1:8080 (the whole stack's default). If a
healthy local-ai already answers there, it is reused; if the port is held by
anything else, setup reports a clear error instead of relocating endpoints.
"""

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

import httpx
import yaml

PORT = 8080
BASE_URL = f"http://127.0.0.1:{PORT}"
MIN_FREE_BYTES = 15 * 1024**3  # ~10 GB models + headroom

_lock = threading.Lock()
_state: dict = {"phase": "not_installed", "detail": None, "progress": None}
_install_thread: threading.Thread | None = None
_server_proc: subprocess.Popen | None = None


# --- paths -----------------------------------------------------------------


def _ai_dir() -> Path | None:
    path = os.environ.get("SECONDBRAIN_AI_DIR")
    return Path(path) if path else None


def _layout() -> dict[str, Path] | None:
    """All interesting paths, or None when the packaged contract is absent."""
    ai = _ai_dir()
    uv_bin = os.environ.get("SECONDBRAIN_UV_BIN")
    wheel = os.environ.get("SECONDBRAIN_LOCALAI_WHEEL")
    template = os.environ.get("SECONDBRAIN_LOCALAI_CONFIG")
    if not (ai and uv_bin and wheel and template):
        return None
    ai = Path(ai)
    return {
        "ai": ai,
        "venv_python": ai / "venv" / "bin" / "python",
        "config": ai / "config" / "config.yaml",
        "models": ai / "models" / "hub",
        "logs": ai / "logs",
        "uv": Path(uv_bin),
        "wheel": Path(wheel),
        "template": Path(template),
    }


def model_repos() -> list[str]:
    """Model repo ids from the config template (single source of truth)."""
    layout = _layout()
    if layout is None:
        return []
    try:
        cfg = yaml.safe_load(layout["template"].read_text())
        return [m["repo"] for m in cfg.get("models", {}).values() if m.get("repo")]
    except Exception:
        return []


# --- model cache -----------------------------------------------------------


def _repo_cached(repo: str, cache_dir: Path) -> bool:
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(repo, cache_dir=str(cache_dir), local_files_only=True)
        return True
    except Exception:
        return False


def _models_complete(cache_dir: Path) -> bool:
    return all(_repo_cached(repo, cache_dir) for repo in model_repos())


def _dir_size(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            continue
    return total


def _expected_total() -> int | None:
    try:
        from huggingface_hub import HfApi

        api = HfApi()
        return sum(
            (s.size or 0)
            for repo in model_repos()
            for s in api.model_info(repo, files_metadata=True).siblings or []
        )
    except Exception:
        return None


# --- server ----------------------------------------------------------------


def server_healthy(timeout: float = 1.5) -> bool:
    try:
        response = httpx.get(f"{BASE_URL}/health", timeout=timeout)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def start_server() -> str:
    """Start the installed server (or attach to a healthy one). Idempotent."""
    layout = _layout()
    if layout is None:
        return "unavailable"
    if server_healthy():
        return "already-running"
    global _server_proc
    if _server_proc is not None and _server_proc.poll() is None:
        return "already-running"

    log_file = layout["logs"] / "server.log"
    layout["logs"].mkdir(parents=True, exist_ok=True)
    with open(log_file, "ab") as log:
        _server_proc = subprocess.Popen(
            [str(layout["venv_python"]), "-m", "localai.server"],
            cwd=str(layout["ai"]),
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env={
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "HOME": os.environ.get("HOME", str(layout["ai"])),
                "LOCAL_AI_HOME": str(layout["ai"]),
                "LOCAL_AI_CONFIG": str(layout["config"]),
                "HF_HOME": str(layout["models"].parent),
            },
        )
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if _server_proc.poll() is not None:
            return f"server exited during startup (code {_server_proc.returncode})"
        if server_healthy():
            return "started"
        time.sleep(1.0)
    return "timeout"


def stop_server() -> None:
    global _server_proc
    if _server_proc is None:
        return
    if _server_proc.poll() is None:
        _server_proc.terminate()
        try:
            _server_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _server_proc.kill()
    _server_proc = None


# --- install ---------------------------------------------------------------


def _set_phase(phase: str, detail: str | None = None, progress: dict | None = None) -> None:
    with _lock:
        _state["phase"] = phase
        _state["detail"] = detail
        _state["progress"] = progress


def install() -> None:
    """Background install: venv → wheel → models → config. Resumable."""
    layout = _layout()
    assert layout is not None  # guarded by routes
    try:
        free = shutil.disk_usage(layout["ai"]).free
        if free < MIN_FREE_BYTES:
            _set_phase("error", f"Not enough free disk space (~15 GB needed, {free / 1024**3:.0f} GB available)")
            return

        repos = model_repos()
        total = _expected_total()
        with _lock:
            _state["progress"] = {"bytes_done": _dir_size(layout["models"]), "bytes_total": total, "current_repo": None}

        # 1. Runtime venv + wheel (skipped when already present).
        if not layout["venv_python"].exists():
            _set_phase("installing", "Preparing the AI engine")
            env = {
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "HOME": os.environ.get("HOME", str(layout["ai"])),
                "UV_PYTHON_INSTALL_DIR": str(layout["ai"] / "python"),
                "UV_CACHE_DIR": str(layout["ai"] / "uv-cache"),
                "HF_HUB_DISABLE_TELEMETRY": "1",
                "DO_NOT_TRACK": "1",
            }
            subprocess.run(
                [str(layout["uv"]), "venv", str(layout["ai"] / "venv"), "--python", "3.12"],
                check=True, capture_output=True, text=True, env=env,
            )
            subprocess.run(
                [str(layout["uv"]), "pip", "install", "--python", str(layout["venv_python"]),
                 str(layout["wheel"])],
                check=True, capture_output=True, text=True, env=env,
            )

        # 2. Models — snapshot_download resumes interrupted files.
        for repo in repos:
            if _repo_cached(repo, layout["models"]):
                continue
            from huggingface_hub import snapshot_download

            _set_phase("installing", f"Downloading {repo}")
            done = _dir_size(layout["models"])
            with _lock:
                _state["progress"] = {"bytes_done": done, "bytes_total": total, "current_repo": repo}
            snapshot_download(repo, cache_dir=str(layout["models"]))

        # 3. Config + first boot.
        layout["config"].parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(layout["template"], layout["config"])
        result = start_server()
        if result not in ("started", "already-running"):
            _set_phase("error", f"AI server failed to start: {result}")
            return
        _set_phase("ready")
    except Exception as exc:  # surface anything to the setup UI
        _set_phase("error", f"{type(exc).__name__}: {exc}")
        raise


def begin_install() -> bool:
    """Start the install thread; False if one is already running."""
    global _install_thread
    with _lock:
        if _state["phase"] == "installing":
            return False
        _state["phase"] = "installing"
        _state["detail"] = "Starting"
    _install_thread = threading.Thread(target=install, name="ai-install", daemon=True)
    _install_thread.start()
    return True


# --- status ----------------------------------------------------------------


def status() -> dict:
    layout = _layout()
    if layout is None:
        return {"available": False, "phase": "unavailable"}
    with _lock:
        phase = _state["phase"]
        detail = _state["detail"]
        progress = _state["progress"]
    installed = layout["venv_python"].exists() and _models_complete(layout["models"])
    if phase not in ("installing", "error"):
        phase = "ready" if installed else "not_installed"
        if phase == "ready":
            detail = None
        elif progress is None and layout["models"].exists():
            progress = {
                "bytes_done": _dir_size(layout["models"]),
                "bytes_total": _expected_total(),
                "current_repo": None,
            }
    return {
        "available": True,
        "phase": phase,
        "detail": detail,
        "progress": progress,
        "server_online": server_healthy(),
        "free_gb": shutil.disk_usage(layout["ai"]).free / 1024**3 if layout["ai"].exists() else None,
    }
