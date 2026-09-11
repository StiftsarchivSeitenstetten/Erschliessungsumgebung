"""FastAPI dependencies for authentication and authorization."""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..auth.sessions import get_session_by_token
from ..config import Settings, get_settings
from ..database import get_db
from ..models import SessionToken, User
from ..permissions import has_module_access


def get_app_settings() -> Settings:
    return get_settings()


def db_session() -> Generator[Session, None, None]:
    yield from get_db()


def current_session(
    request: Request,
    db: Session = Depends(db_session),
    settings: Settings = Depends(get_app_settings),
) -> SessionToken:
    token = request.cookies.get(settings.cookie_name)
    session = get_session_by_token(db, token)
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet.")
    return session


def require_authenticated_user(session: SessionToken = Depends(current_session)) -> User:
    user = session.user
    if not user.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet.")
    return user


def require_csrf(
    request: Request,
    x_csrf_token: str | None = Header(default=None, alias="X-CSRF-Token"),
    session: SessionToken = Depends(current_session),
    settings: Settings = Depends(get_app_settings),
) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
    if not x_csrf_token or not csrf_cookie or x_csrf_token != csrf_cookie or x_csrf_token != session.csrf_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF-Prüfung fehlgeschlagen.")


def require_role(*roles: str):
    def dependency(user: User = Depends(require_authenticated_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Keine Berechtigung.")
        return user

    return dependency


def require_module_access(module_key: str):
    def dependency(user: User = Depends(require_authenticated_user)) -> User:
        if not has_module_access(user, module_key):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Arbeitsbereich nicht freigegeben.")
        return user

    return dependency
