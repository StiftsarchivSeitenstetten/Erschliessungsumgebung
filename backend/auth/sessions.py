"""Opaque server-side session handling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SessionToken, User


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, user: User, lifetime_seconds: int) -> tuple[str, SessionToken]:
    token = secrets.token_urlsafe(48)
    session = SessionToken(
        token_hash=hash_session_token(token),
        csrf_token=secrets.token_urlsafe(32),
        user_id=user.id,
        expires_at=utcnow() + timedelta(seconds=lifetime_seconds),
    )
    db.add(session)
    return token, session


def get_session_by_token(db: Session, token: str | None) -> SessionToken | None:
    if not token:
        return None
    session = db.scalar(select(SessionToken).where(SessionToken.token_hash == hash_session_token(token)))
    if not session or session.invalidated_at is not None:
        return None
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= utcnow():
        return None
    return session


def invalidate_session(db: Session, session: SessionToken) -> None:
    session.invalidated_at = utcnow()
    db.add(session)
