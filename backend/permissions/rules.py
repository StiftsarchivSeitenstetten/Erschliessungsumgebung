"""Role and module authorization rules."""

from __future__ import annotations

from typing import Any

from ..models import User


ROLE_EHRENAMTLICH = "ehrenamtlich"
ROLE_REDAKTION = "redaktion"
ROLE_ADMIN = "admin"
ROLES = {ROLE_EHRENAMTLICH, ROLE_REDAKTION, ROLE_ADMIN}

RECORD_STAGE_EHRENAMTLICH = "ehrenamtlich"
RECORD_STAGE_REDAKTIONELL = "redaktionell"
MODULE_FOTO_PAPIERABZUEGE = "foto_papierabzuege"
MODULES = {MODULE_FOTO_PAPIERABZUEGE}

UI_PROFILES = {"ehrenamt-standard", "ehrenamt-barrierearm", "redaktion"}


def has_module_access(user: User, module_key: str) -> bool:
    return module_key in user.modules


def role_allows_user_admin(role: str) -> bool:
    return role == ROLE_ADMIN


def can_edit_record(user: User, record: dict[str, Any]) -> bool:
    stage = record.get("redaktion", {}).get("stufe")
    if user.role in {ROLE_ADMIN, ROLE_REDAKTION}:
        return stage in {RECORD_STAGE_EHRENAMTLICH, RECORD_STAGE_REDAKTIONELL}
    if user.role == ROLE_EHRENAMTLICH:
        return stage == RECORD_STAGE_EHRENAMTLICH
    return False


def validate_role(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"Unbekannte Rolle: {role}")
    return role


def validate_module(module_key: str) -> str:
    if module_key not in MODULES:
        raise ValueError(f"Unbekannter Arbeitsbereich: {module_key}")
    return module_key


def validate_ui_profile(ui_profile: str) -> str:
    if ui_profile not in UI_PROFILES:
        raise ValueError(f"Unbekanntes UI-Profil: {ui_profile}")
    return ui_profile
