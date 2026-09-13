"""Load declarative module metadata without binding it to one object type."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from ..config import ROOT


MODULE_DIR = ROOT / "ui" / "modules"


@dataclass(frozen=True)
class ModuleDefinition:
    id: str
    access_key: str
    label: str
    schema_path: Path
    fachkonfiguration_path: Path | None
    datensatz_typ: str | None
    form_fields: tuple[str, ...]
    search_fields: tuple[str, ...]
    list_fields: tuple[str, ...]
    presettable_fields: tuple[str, ...]
    field_rights: dict[str, dict[str, Any]]
    signature_strategy: dict[str, Any]
    vocabularies: dict[str, Any]

    def public_metadata(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "module": self.access_key,
            "label": self.label,
            "datensatz_typ": self.datensatz_typ,
            "form_fields": list(self.form_fields),
            "search_fields": list(self.search_fields),
            "list_fields": list(self.list_fields),
        }


def _resolve_path(base: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return (base / path).resolve()


def _load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Modulkonfiguration ist kein Mapping: {path}")
    return data


def _load_json_like_yaml(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Fachkonfiguration ist kein Mapping: {path}")
    return data


def _field_rights(raw_module: dict[str, Any], fachkonfiguration: dict[str, Any]) -> dict[str, dict[str, Any]]:
    configured = raw_module.get("field_rights")
    if isinstance(configured, dict):
        return configured

    rights: dict[str, dict[str, Any]] = {}
    for profile in fachkonfiguration.get("ui_profiles", {}).values():
        role = profile.get("role")
        if role == "ehrenamt":
            role = "ehrenamtlich"
        if not role:
            continue
        for field in profile.get("editable_fields", []):
            rights.setdefault(field, {"read": [], "write": []})
            if role not in rights[field]["write"]:
                rights[field]["write"].append(role)
            if role not in rights[field]["read"]:
                rights[field]["read"].append(role)
    return rights


def load_module(path: Path) -> ModuleDefinition:
    raw = _load_yaml(path)
    base = path.parent
    fachkonfiguration_path = _resolve_path(base, raw.get("fachkonfiguration"))
    fachkonfiguration = _load_json_like_yaml(fachkonfiguration_path)
    schema_path = _resolve_path(base, raw.get("schema"))
    if schema_path is None:
        raise ValueError(f"Modulkonfiguration ohne schema: {path}")

    module_id = raw["id"]
    access_key = raw.get("access_key") or module_id
    signature = raw.get("signature_strategy") or fachkonfiguration.get("signature") or {}
    presettable = raw.get("presettable_fields") or fachkonfiguration.get("presettable_fields") or []
    vocabularies = raw.get("vocabularies") or fachkonfiguration.get("vocabularies") or {}

    return ModuleDefinition(
        id=module_id,
        access_key=access_key,
        label=raw.get("label") or fachkonfiguration.get("module_label") or module_id,
        schema_path=schema_path,
        fachkonfiguration_path=fachkonfiguration_path,
        datensatz_typ=raw.get("datensatz_typ") or fachkonfiguration.get("datensatz_typ"),
        form_fields=tuple(raw.get("form_fields") or ()),
        search_fields=tuple(raw.get("search_fields") or ()),
        list_fields=tuple(raw.get("list_fields") or ()),
        presettable_fields=tuple(presettable),
        field_rights=_field_rights(raw, fachkonfiguration),
        signature_strategy=signature,
        vocabularies=vocabularies,
    )


@lru_cache(maxsize=1)
def list_modules() -> tuple[ModuleDefinition, ...]:
    return tuple(load_module(path) for path in sorted(MODULE_DIR.glob("*.yaml")))


def get_module(access_key: str) -> ModuleDefinition:
    for module in list_modules():
        if module.access_key == access_key or module.id == access_key:
            return module
    raise KeyError(access_key)
