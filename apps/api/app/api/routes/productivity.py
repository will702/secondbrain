from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession

from app.agents.productivity import QuickCommandError, parse_quick_command
from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import User

router = APIRouter(tags=["productivity"])


class QuickCommand(BaseModel):
    text: str


@router.post("/quick-command")
def quick_command(
    body: QuickCommand, user: User = Depends(get_current_user), db: OrmSession = Depends(get_db)
):
    """Turn one sentence into a pending proposal. Executes nothing."""
    try:
        proposal = parse_quick_command(db, user, body.text)
    except QuickCommandError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    return {
        "proposal_id": str(proposal.id),
        "action_type": proposal.action_type,
        "payload": proposal.payload,
        "risk_level": proposal.risk_level.value,
        "status": proposal.status.value,
    }
