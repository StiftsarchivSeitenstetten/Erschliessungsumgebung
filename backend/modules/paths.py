"""Small path helpers for canonical record dictionaries.

Path syntax v1 is intentionally simple: dot-separated object keys such as
``erschliessung.beschriftung`` or ``technik.erstellt_am``. Repeated data is
described by field metadata, not by an XPath-like expression language.
"""

from __future__ import annotations

from typing import Any


MISSING = object()


def split_path(path: str) -> list[str]:
    parts = path.split(".")
    if not path or any(not part for part in parts):
        raise ValueError(f"Ungueltiger Feldpfad: {path}")
    return parts


def get_path_value(data: dict[str, Any], path: str, default: Any = MISSING) -> Any:
    current: Any = data
    for part in split_path(path):
        if not isinstance(current, dict) or part not in current:
            if default is MISSING:
                raise KeyError(path)
            return default
        current = current[part]
    return current


def path_exists(data: dict[str, Any], path: str) -> bool:
    sentinel = object()
    return get_path_value(data, path, default=sentinel) is not sentinel


def set_path_value(data: dict[str, Any], path: str, value: Any, *, create_missing: bool = True) -> None:
    parts = split_path(path)
    current: dict[str, Any] = data
    for part in parts[:-1]:
        child = current.get(part)
        if child is None:
            if not create_missing:
                raise KeyError(path)
            child = {}
            current[part] = child
        if not isinstance(child, dict):
            raise TypeError(f"Pfadsegment ist kein Objekt: {part}")
        current = child
    current[parts[-1]] = value
