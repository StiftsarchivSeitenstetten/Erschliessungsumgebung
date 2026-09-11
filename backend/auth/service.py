"""User lookup and login service."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import ModuleAccess, User
from ..permissions.rules import validate_module, validate_role, validate_ui_profile
from .passwords import hash_password, verify_password


def normalize_email(email: str) -> str:
    return email.strip().lower()


def find_user_by_login(db: Session, login: str) -> User | None:
    login = login.strip()
    return db.scalar(
        select(User).where(or_(User.username == login, User.email == normalize_email(login)))
    )


def create_user(
    db: Session,
    *,
    username: str,
    display_name: str,
    email: str,
    role: str,
    ui_profile: str,
    modules: list[str],
    password: str,
    active: bool = True,
) -> User:
    validate_role(role)
    validate_ui_profile(ui_profile)
    module_keys = sorted({validate_module(module) for module in modules})
    user = User(
        username=username.strip(),
        display_name=display_name.strip(),
        email=normalize_email(email),
        password_hash=hash_password(password),
        role=role,
        active=active,
        ui_profile=ui_profile,
    )
    user.module_access = [ModuleAccess(module_key=module) for module in module_keys]
    db.add(user)
    db.flush()
    return user


def authenticate_user(db: Session, login: str, password: str) -> User | None:
    user = find_user_by_login(db, login)
    if not user or not user.active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login = datetime.now(timezone.utc)
    db.add(user)
    return user
