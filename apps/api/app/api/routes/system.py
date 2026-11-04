"""System visibility + the PMAX bridge. Read-only except the two one-row PMAX
decisions, which are explicit user clicks (never batched) and are audited."""

from datetime import datetime
from urllib.parse import urlparse

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session as OrmSession

from app.api.deps import get_current_user, is_instance_owner
from app.core.config import get_settings
from app.core.db import get_db
from app.models import ActionProposal, AgentRun, AuditLog, Integration, Job, User
from app.models.enums import ProposalStatus
from app.services import ai_stack, system_status
from app.services.integrations import pmax

router = APIRouter(tags=["system"])


def _require_same_origin(request: Request) -> None:
    """Cookie is SameSite=lax; belt and braces for the file-mutating POSTs."""
    origin = request.headers.get("origin")
    if origin is None:
        return
    allowed = set(get_settings().frontend_origins)
    host = urlparse(origin)
    if origin in allowed or host.netloc == request.headers.get("host"):
        return
    raise HTTPException(403, "Cross-origin request refused")


@router.get("/system/status")
def system_overview(user: User = Depends(get_current_user), db: OrmSession = Depends(get_db)):
    jobs = dict(
        db.execute(
            sa.select(Job.status, sa.func.count()).where(Job.user_id == user.id).group_by(Job.status)
        ).all()
    )
    runs = (
        db.execute(
            sa.select(AgentRun)
            .where(AgentRun.user_id == user.id)
            .order_by(AgentRun.created_at.desc())
            .limit(10)
        )
        .scalars()
        .all()
    )
    integrations = (
        db.execute(sa.select(Integration).where(Integration.user_id == user.id)).scalars().all()
    )
    pending = db.execute(
        sa.select(sa.func.count())
        .select_from(ActionProposal)
        .where(ActionProposal.user_id == user.id, ActionProposal.status == ProposalStatus.pending)
    ).scalar_one()
    load = system_status.booked_load(db, user)
    owner = is_instance_owner(db, user)
    if owner:
        pmax.write_load_snapshot(load)
    return {
        "jobs": {str(k.value if hasattr(k, "value") else k): v for k, v in jobs.items()},
        "recent_runs": [
            {
                "agent": r.agent,
                "purpose": r.purpose,
                "model": r.model,
                "status": r.status,
                "latency_ms": r.latency_ms,
                "error": r.error,
                "at": r.created_at,
            }
            for r in runs
        ],
        "ai": ai_stack.status(),
        "integrations": [
            {"provider": i.provider, "status": i.status, "last_synced_at": i.last_synced_at}
            for i in integrations
        ],
        "pmax": pmax.status() if owner else {"available": False, "error": "owner only"},
        "pending_proposals": pending,
        "load": load,
    }


@router.get("/system/activity")
def system_activity(
    limit: int = Query(30, ge=1, le=100),
    before: datetime | None = None,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    return {"items": system_status.activity_feed(db, user, limit=limit, before=before)}


@router.get("/system/load")
def system_load(user: User = Depends(get_current_user), db: OrmSession = Depends(get_db)):
    load = system_status.booked_load(db, user)
    if is_instance_owner(db, user):
        pmax.write_load_snapshot(load)
    return load


def _require_owner(db: OrmSession, user: User) -> None:
    if not is_instance_owner(db, user):
        raise HTTPException(403, "Only the instance owner can manage file actions")


@router.get("/pmax/pending")
def pmax_pending(user: User = Depends(get_current_user), db: OrmSession = Depends(get_db)):
    _require_owner(db, user)
    try:
        return pmax.pending()
    except pmax.PmaxUnavailable as exc:
        raise HTTPException(503, f"PMAX unavailable: {exc}") from exc


def _decide(
    plan: str, row_id: str, approve: bool, request: Request, user: User, db: OrmSession
) -> dict:
    _require_owner(db, user)
    _require_same_origin(request)
    try:
        pmax.decide_row(plan, row_id, approve)
    except pmax.PmaxRejected as exc:
        raise HTTPException(409, str(exc)) from exc
    except pmax.PmaxUnavailable as exc:
        raise HTTPException(503, f"PMAX unavailable: {exc}") from exc
    db.add(
        AuditLog(
            user_id=user.id,
            actor="user",
            action="pmax.approve" if approve else "pmax.reject",
            object_type="pmax_row",
            object_id=row_id,
            detail={"plan": plan},
        )
    )
    db.commit()
    return {"ok": True, "decision": "approved" if approve else "rejected"}


@router.post("/pmax/pending/{plan}/{row_id}/approve")
def pmax_approve(
    plan: str,
    row_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    return _decide(plan, row_id, True, request, user, db)


@router.post("/pmax/pending/{plan}/{row_id}/reject")
def pmax_reject(
    plan: str,
    row_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    return _decide(plan, row_id, False, request, user, db)
