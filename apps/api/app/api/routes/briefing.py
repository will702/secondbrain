import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import AuditLog, User
from app.services.briefing.morning import build_briefing
from app.services.proposals import service as proposals_service

router = APIRouter(tags=["briefing"])


@router.get("/briefing")
def morning_briefing(user: User = Depends(get_current_user), db: OrmSession = Depends(get_db)):
    return build_briefing(db, user)


class ProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action_type: str
    payload: dict
    reason: str
    evidence: dict | None
    risk_level: str
    proposed_by: str
    status: str
    created_at: object


@router.get("/proposals", response_model=list[ProposalOut])
def list_proposals(
    status_filter: str | None = None,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    return proposals_service.list_proposals(db, user, status_filter)


class ProposalDecision(BaseModel):
    decision: str  # approve | reject | modify
    modified_payload: dict | None = None


@router.post("/proposals/{proposal_id}/decide")
def decide_proposal(
    proposal_id: uuid.UUID,
    body: ProposalDecision,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    proposal = db.get(proposals_service.ActionProposal, proposal_id)
    if proposal is None or proposal.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    try:
        result = proposals_service.decide(db, user, proposal, body.decision, body.modified_payload)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {
        "id": str(result.id),
        "status": result.status.value,
        "executed_at": result.executed_at.isoformat() if result.executed_at else None,
    }


class BatchApprove(BaseModel):
    proposal_ids: list[uuid.UUID]


@router.post("/proposals/approve-batch")
def approve_batch(
    body: BatchApprove,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    results = []
    for proposal_id in body.proposal_ids:
        proposal = db.get(proposals_service.ActionProposal, proposal_id)
        if proposal is None or proposal.user_id != user.id:
            results.append({"id": str(proposal_id), "status": "not_found"})
            continue
        try:
            decided = proposals_service.decide(db, user, proposal, "approve")
            results.append({"id": str(decided.id), "status": decided.status.value})
        except ValueError as exc:
            results.append({"id": str(proposal_id), "status": "error", "detail": str(exc)})
    return {"results": results}


@router.get("/audit")
def audit_log(
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    rows = (
        db.execute(
            select(AuditLog)
            .where(AuditLog.user_id == user.id)
            .order_by(AuditLog.created_at.desc())
            .limit(min(limit, 500))
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "actor": row.actor,
            "action": row.action,
            "object_type": row.object_type,
            "object_id": row.object_id,
            "detail": row.detail,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
