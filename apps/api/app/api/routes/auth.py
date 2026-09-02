from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.api.deps import get_current_user
from app.api.schemas import LoginRequest, RegisterRequest, UserOut
from app.core.db import get_db
from app.core.security import (
    COOKIE_NAME,
    hash_password,
    hash_token,
    new_session_token,
    session_expiry,
    verify_password,
)
from app.models import AuditLog, DbSession, User

router = APIRouter(prefix="/auth", tags=["auth"])


def _audit(db: OrmSession, user_id, action: str, detail: dict | None = None) -> None:
    db.add(AuditLog(user_id=user_id, actor="user", action=action, detail=detail))


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        raw_token,
        httponly=True,
        samesite="lax",
        secure=False,  # True when served over HTTPS (production)
        max_age=30 * 24 * 3600,
        path="/",
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(body: RegisterRequest, response: Response, db: OrmSession = Depends(get_db)):
    existing = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        timezone=body.timezone,
    )
    db.add(user)
    db.flush()
    raw, token_hash = new_session_token()
    db.add(DbSession(user_id=user.id, token_hash=token_hash, expires_at=session_expiry()))
    _audit(db, user.id, "auth.register", {"email": user.email})
    db.commit()
    _set_session_cookie(response, raw)
    return user


@router.post("/login", response_model=UserOut)
def login(body: LoginRequest, response: Response, db: OrmSession = Depends(get_db)):
    user = db.execute(select(User).where(User.email == body.email)).scalar_one_or_none()
    if user is None or not verify_password(user.password_hash, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    raw, token_hash = new_session_token()
    db.add(DbSession(user_id=user.id, token_hash=token_hash, expires_at=session_expiry()))
    _audit(db, user.id, "auth.login")
    db.commit()
    _set_session_cookie(response, raw)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: OrmSession = Depends(get_db),
):
    from app.core.security import hash_token as _hash

    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        session = db.execute(
            select(DbSession).where(DbSession.token_hash == _hash(cookie))
        ).scalar_one_or_none()
        if session:
            db.delete(session)
    _audit(db, user.id, "auth.logout")
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


def utcnow() -> datetime:
    return datetime.now(UTC)
