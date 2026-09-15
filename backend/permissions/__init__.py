"""Central authorization rules."""

from .rules import (
    MODULE_AUTOGRAPHEN_9_6,
    MODULE_FOTO_PAPIERABZUEGE,
    ROLE_ADMIN,
    ROLE_EHRENAMTLICH,
    ROLE_REDAKTION,
    can_edit_record,
    has_module_access,
    role_allows_user_admin,
)

__all__ = [
    "MODULE_AUTOGRAPHEN_9_6",
    "MODULE_FOTO_PAPIERABZUEGE",
    "ROLE_ADMIN",
    "ROLE_EHRENAMTLICH",
    "ROLE_REDAKTION",
    "can_edit_record",
    "has_module_access",
    "role_allows_user_admin",
]
