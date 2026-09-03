from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession

from app.agents.ask_agent import answer_question
from app.api.deps import get_current_user
from app.core.db import get_db
from app.models import User
from app.services.retrieval.hybrid import search_chunks

router = APIRouter(tags=["search"])


class SearchResult(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str | None
    section: str | None
    page: int | None
    text: str
    matched_signals: list[str]
    score: float


@router.get("/search", response_model=list[SearchResult])
def search(
    q: str,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
    limit: int = 10,
):
    return search_chunks(db, user.id, q, limit=limit)


class AskRequest(BaseModel):
    question: str


@router.post("/ask")
def ask(
    body: AskRequest,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    result = answer_question(db, user, body.question)
    return result.model_dump()
