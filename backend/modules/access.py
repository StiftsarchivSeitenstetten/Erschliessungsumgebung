"""Generic field access helpers for module runtime definitions."""

from __future__ import annotations

from collections.abc import Iterable


SERVER_MANAGED_FIELDS = frozenset({
    "id",
    "base_revision",
    "revision",
    "technik.erstellt_am",
    "technik.erstellt_von",
    "technik.geaendert_am",
    "technik.geaendert_von",
})


def role_allowed(role: str, roles: Iterable[str]) -> bool:
    return role in set(roles)


def is_server_managed_field(path: str) -> bool:
    return path in SERVER_MANAGED_FIELDS
