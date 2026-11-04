from datetime import UTC, datetime

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.core.db import get_db
from app.core.security import COOKIE_NAME
from app.models import DbSession, User


def is_instance_owner(db: OrmSession, user: User) -> bool:
    """PMAX state belongs to the OS user, not to an app account: only the first
    account (the person who set the instance up) may see or decide file actions."""
    first = db.execute(select(User.id).order_by(User.created_at, User.id).limit(1)).scalar_one_or_none()
    return first == user.id


def get_current_user(
    request: Request,
    sb_session: str | None = Cookie(default=None, alias=COOKIE_NAME),
    db: OrmSession = Depends(get_db),
) -> User:
    if not sb_session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    from app.core.security import hash_token

    session = db.execute(
        select(DbSession).where(DbSession.token_hash == hash_token(sb_session))
    ).scalar_one_or_none()
    if session is None or session.expires_at < datetime.now(UTC):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session invalid or expired")

    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    request.state.session_id = session.id
    return user
