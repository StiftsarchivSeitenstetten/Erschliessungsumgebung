"""Load declarative module metadata without binding it to one object type."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from ..config import ROOT


MODULE_DIR = ROOT / "ui" / "modules"
MODULE_CONFIG_SCHEMA_PATH = ROOT / "schemas" / "module-config.schema.json"
CORE_DATATYPES_SCHEMA_PATH = ROOT / "schemas" / "core-datatypes.schema.json"
VOCABULARY_SCHEMA_PATH = ROOT / "schemas" / "vocabulary.schema.json"


class ModuleConfigError(ValueError):
    pass


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


def _load_schema(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ModuleConfigError(f"Schema ist kein Mapping: {path}")
    return data


def validate_json_schema(path: Path) -> None:
    try:
        jsonschema.Draft202012Validator.check_schema(_load_schema(path))
    except jsonschema.SchemaError as exc:
        raise ModuleConfigError(f"Ungueltiges JSON Schema {path}: {exc.message}") from exc


def validate_vocabulary(data: dict[str, Any], schema_path: Path = VOCABULARY_SCHEMA_PATH) -> None:
    try:
        jsonschema.validate(instance=data, schema=_load_schema(schema_path))
    except jsonschema.ValidationError as exc:
        raise ModuleConfigError(f"Ungueltiges Vokabular: {exc.message}") from exc


def validate_core_schemas() -> None:
    validate_json_schema(CORE_DATATYPES_SCHEMA_PATH)
    validate_json_schema(VOCABULARY_SCHEMA_PATH)
    validate_json_schema(MODULE_CONFIG_SCHEMA_PATH)


def _field_rights(raw_module: dict[str, Any], fachkonfiguration: dict[str, Any]) -> dict[str, dict[str, Any]]:
    access_fields = raw_module.get("access", {}).get("fields")
    if isinstance(access_fields, dict):
        return access_fields

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


def _module_id(raw: dict[str, Any]) -> str:
    module = raw.get("module")
    if isinstance(module, dict):
        return str(module["id"])
    return str(raw["id"])


def _access_key(raw: dict[str, Any]) -> str:
    module = raw.get("module")
    if isinstance(module, dict):
        return str(module.get("access_key") or module["id"])
    return str(raw.get("access_key") or raw["id"])


def _schema_ref(raw: dict[str, Any]) -> str | None:
    schema = raw.get("schema")
    if isinstance(schema, dict):
        return schema.get("path")
    if isinstance(schema, str):
        return schema
    return raw.get("schema_path")


def _form_fields(raw: dict[str, Any]) -> tuple[str, ...]:
    if isinstance(raw.get("form"), dict):
        fields: list[str] = []
        for section in raw["form"].get("sections", []):
            for field in section.get("fields", []):
                fields.append(field["path"])
            for group in section.get("groups", []) or []:
                for field in group.get("fields", []):
                    fields.append(field["path"])
        return tuple(fields)
    return tuple(raw.get("form_fields") or ())


def _search_fields(raw: dict[str, Any]) -> tuple[str, ...]:
    search = raw.get("search")
    if isinstance(search, dict):
        return tuple(search.get("fulltext") or ())
    return tuple(raw.get("search_fields") or ())


def _list_fields(raw: dict[str, Any]) -> tuple[str, ...]:
    listing = raw.get("list")
    if isinstance(listing, dict):
        return tuple(column["path"] for column in listing.get("columns", []))
    return tuple(raw.get("list_fields") or ())


def _presettable_fields(raw: dict[str, Any], fachkonfiguration: dict[str, Any]) -> tuple[str, ...]:
    presets = raw.get("presets")
    if isinstance(presets, dict):
        return tuple(presets.get("enabled_fields") or ())
    return tuple(raw.get("presettable_fields") or fachkonfiguration.get("presettable_fields") or ())


def validate_module_config(raw: dict[str, Any], path: Path) -> None:
    if raw.get("config_version") != 1:
        raise ModuleConfigError(f"Modulkonfiguration {path} hat keine unterstuetzte config_version.")
    try:
        jsonschema.validate(instance=raw, schema=_load_schema(MODULE_CONFIG_SCHEMA_PATH))
    except jsonschema.ValidationError as exc:
        raise ModuleConfigError(f"Ungueltige Modulkonfiguration {path}: {exc.message}") from exc

    schema_path = _resolve_path(path.parent, _schema_ref(raw))
    if schema_path is None or not schema_path.exists():
        raise ModuleConfigError(f"Referenziertes Datenschema fehlt: {path}")


def load_module(path: Path) -> ModuleDefinition:
    raw = _load_yaml(path)
    if "config_version" in raw:
        validate_module_config(raw, path)
    base = path.parent
    fachkonfiguration_path = _resolve_path(base, raw.get("fachkonfiguration"))
    fachkonfiguration = _load_json_like_yaml(fachkonfiguration_path)
    schema_path = _resolve_path(base, _schema_ref(raw))
    if schema_path is None:
        raise ValueError(f"Modulkonfiguration ohne schema: {path}")

    module_data = raw.get("module") if isinstance(raw.get("module"), dict) else {}
    module_id = _module_id(raw)
    access_key = _access_key(raw)
    signature = raw.get("signature") or raw.get("signature_strategy") or fachkonfiguration.get("signature") or {}
    vocabularies = raw.get("vocabularies") or fachkonfiguration.get("vocabularies") or {}

    return ModuleDefinition(
        id=module_id,
        access_key=access_key,
        label=module_data.get("label") or raw.get("label") or fachkonfiguration.get("module_label") or module_id,
        schema_path=schema_path,
        fachkonfiguration_path=fachkonfiguration_path,
        datensatz_typ=module_data.get("record_type") or raw.get("datensatz_typ") or fachkonfiguration.get("datensatz_typ"),
        form_fields=_form_fields(raw),
        search_fields=_search_fields(raw),
        list_fields=_list_fields(raw),
        presettable_fields=_presettable_fields(raw, fachkonfiguration),
        field_rights=_field_rights(raw, fachkonfiguration),
        signature_strategy=signature,
        vocabularies=vocabularies,
    )


def load_modules(paths: list[Path] | tuple[Path, ...]) -> tuple[ModuleDefinition, ...]:
    sorted_paths = sorted(paths)
    modules = tuple(load_module(path) for path in sorted_paths)
    seen: dict[str, int] = {}
    for index, module in enumerate(modules):
        for key in (module.id, module.access_key):
            if key in seen and seen[key] != index:
                raise ModuleConfigError(f"Doppelte Modul-ID oder Zugriffkennung: {key}")
            seen[key] = index
    return modules


@lru_cache(maxsize=1)
def list_modules() -> tuple[ModuleDefinition, ...]:
    validate_core_schemas()
    return load_modules(tuple(MODULE_DIR.glob("*.yaml")))


def get_module(access_key: str) -> ModuleDefinition:
    for module in list_modules():
        if module.access_key == access_key or module.id == access_key:
            return module
    raise KeyError(access_key)
