"""Guided AI setup: install status / start install / start-stop the server."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.services import ai_stack

router = APIRouter(prefix="/ai", tags=["ai"], dependencies=[Depends(get_current_user)])


@router.get("/status")
def ai_status() -> dict:
    return ai_stack.status()


@router.post("/install", status_code=status.HTTP_202_ACCEPTED)
def ai_install():
    current = ai_stack.status()
    if not current["available"]:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI setup is not available in this build")
    if current["phase"] == "installing":
        raise HTTPException(status.HTTP_409_CONFLICT, "Installation already in progress")
    ai_stack.begin_install()
    return {"started": True}


@router.post("/start")
def ai_start():
    current = ai_stack.status()
    if not current["available"]:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI setup is not available in this build")
    if current["phase"] != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "AI is not installed yet")
    result = ai_stack.start_server()
    if result not in ("started", "already-running"):
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, result)
    return {"result": result}


@router.post("/stop")
def ai_stop():
    ai_stack.stop_server()
    return {"stopped": True}
