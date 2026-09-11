"""Authentication API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..auth.service import authenticate_user
from ..auth.rate_limit import login_rate_limiter
from ..auth.sessions import create_session, invalidate_session
from ..config import Settings
from ..models import SessionToken, User
from .deps import current_session, db_session, get_app_settings, require_authenticated_user, require_csrf


router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    login: str
    password: str


class UserResponse(BaseModel):
    id: int
    username: str
    display_name: str
    email: str
    role: str
    ui_profile: str
    modules: list[str]


def user_response(user: User) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        role=user.role,
        ui_profile=user.ui_profile,
        modules=user.modules,
    )


@router.post("/login", response_model=UserResponse)
def login(payload: LoginRequest, response: Response, db: Session = Depends(db_session), settings: Settings = Depends(get_app_settings)) -> UserResponse:
    rate_key = payload.login.strip().lower()
    if login_rate_limiter.is_limited(rate_key):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Anmeldung vorübergehend gesperrt.")
    user = authenticate_user(db, payload.login, payload.password)
    if not user:
        login_rate_limiter.record_failure(rate_key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Benutzername oder Passwort ist falsch.")
    login_rate_limiter.record_success(rate_key)
    session_token, session = create_session(db, user, settings.session_lifetime_seconds)
    db.commit()
    response.set_cookie(
        settings.cookie_name,
        session_token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_lifetime_seconds,
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        session.csrf_token,
        httponly=False,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_lifetime_seconds,
    )
    return user_response(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
def logout(
    response: Response,
    session: SessionToken = Depends(current_session),
    db: Session = Depends(db_session),
    settings: Settings = Depends(get_app_settings),
) -> Response:
    invalidate_session(db, session)
    db.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    response.delete_cookie(settings.cookie_name, httponly=True, samesite="lax", secure=settings.cookie_secure)
    response.delete_cookie(settings.csrf_cookie_name, httponly=False, samesite="lax", secure=settings.cookie_secure)
    return response


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(require_authenticated_user)) -> UserResponse:
    return user_response(user)
