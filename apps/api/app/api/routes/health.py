import logging

import httpx
import sqlalchemy
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.db import engine

logger = logging.getLogger("secondbrain.health")
router = APIRouter()


def _db_status() -> tuple[bool, str]:
    try:
        with engine.connect() as conn:
            conn.execute(sqlalchemy.text("SELECT 1"))
        return True, "ok"
    except Exception as exc:  # pragma: no cover - environment dependent
        return False, f"unreachable: {type(exc).__name__}"


def _llm_status() -> tuple[bool | None, str]:
    """None = not configured/degraded-but-optional. The API works without an LLM."""
    settings = get_settings()
    try:
        response = httpx.get(f"{settings.llm_base_url}/models", timeout=3.0)
        if response.status_code == 200:
            return True, "ok"
        return None, f"http {response.status_code}"
    except Exception:
        return None, "unreachable (optional — ingestion will retry)"


@router.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
def readyz() -> JSONResponse:
    db_ok, db_detail = _db_status()
    llm_ok, llm_detail = _llm_status()
    components = {
        "database": {"ok": db_ok, "detail": db_detail},
        "llm": {"ok": llm_ok, "detail": llm_detail},
    }
    # DB is required; LLM is degradable.
    ready = db_ok
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "degraded", "components": components},
    )
