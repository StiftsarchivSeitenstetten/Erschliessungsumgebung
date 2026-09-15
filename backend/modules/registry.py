"""Load declarative module metadata without binding it to one object type."""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from ..config import ROOT
from ..vocabularies import VocabularyError, load_vocabulary
from .runtime import ModuleDefinition, ModuleField, ModuleSection


MODULE_DIR = ROOT / "ui" / "modules"
MODULE_CONFIG_SCHEMA_PATH = ROOT / "schemas" / "module-config.schema.json"
CORE_DATATYPES_SCHEMA_PATH = ROOT / "schemas" / "core-datatypes.schema.json"
VOCABULARY_SCHEMA_PATH = ROOT / "schemas" / "vocabulary.schema.json"


class ModuleConfigError(ValueError):
    pass


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


def _schema_for_path(schema: dict[str, Any], path: str) -> dict[str, Any]:
    current = schema
    for part in path.split("."):
        properties = current.get("properties") if isinstance(current, dict) else None
        if not isinstance(properties, dict) or part not in properties:
            return {}
        current = properties[part]
    return current if isinstance(current, dict) else {}


def _schema_requires_path(schema: dict[str, Any], path: str) -> bool:
    current = schema
    for part in path.split("."):
        if not isinstance(current, dict) or part not in set(current.get("required") or []):
            return False
        properties = current.get("properties")
        if not isinstance(properties, dict) or part not in properties:
            return False
        current = properties[part]
    return True


def _schema_options(property_schema: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    enum_values = property_schema.get("enum")
    if not isinstance(enum_values, list):
        return ()
    return tuple({"value": value, "label": str(value)} for value in enum_values if value is not None)


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
    ids = [term["id"] for term in data.get("terms", [])]
    duplicates = sorted({term_id for term_id in ids if ids.count(term_id) > 1})
    if duplicates:
        raise ModuleConfigError(f"Doppelte Term-ID(s): {', '.join(duplicates)}")


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
    for field_path, rights in raw.get("access", {}).get("fields", {}).items():
        view_roles = set(rights.get("view") or [])
        edit_roles = set(rights.get("edit") or [])
        if not edit_roles.issubset(view_roles):
            raise ModuleConfigError(f"edit setzt view voraus: {field_path}")


def _field_id(path: str) -> str:
    return path.split(".")[-1].replace("[]", "")


def _field_access(field_path: str, rights: dict[str, dict[str, Any]]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    configured = rights.get(field_path, {})
    view = configured.get("view") or configured.get("read") or []
    edit = configured.get("edit") or configured.get("write") or []
    return tuple(view), tuple(edit)


def _module_field(raw_field: dict[str, Any], section_id: str, rights: dict[str, dict[str, Any]]) -> ModuleField:
    path = raw_field["path"]
    view_roles, edit_roles = _field_access(path, rights)
    item_fields = tuple(
        replace(_module_field(item, section_id, rights={}), view_roles=view_roles, edit_roles=edit_roles)
        for item in raw_field.get("item_fields", []) or []
    )
    return ModuleField(
        id=raw_field.get("id") or _field_id(path),
        path=path,
        label=raw_field["label"],
        widget=raw_field["widget"],
        section=section_id,
        order=int(raw_field.get("order", 0)),
        help=raw_field.get("help"),
        placeholder=raw_field.get("placeholder"),
        presettable=bool(raw_field.get("presettable", False)),
        view_roles=view_roles,
        edit_roles=edit_roles,
        vocabulary=raw_field.get("vocabulary"),
        item_fields=item_fields,
        options=() if raw_field["widget"] == "vocabulary_select" else tuple(raw_field.get("options") or ()),
    )


def _walk_fields(fields: tuple[ModuleField, ...]):
    for field in fields:
        yield field
        yield from _walk_fields(field.item_fields)


def _vocabulary_references(raw: dict[str, Any], config_path: Path) -> dict[str, dict[str, str]]:
    references = raw.get("vocabularies") or {}
    resolved: dict[str, dict[str, str]] = {}
    for vocabulary_id, reference in references.items():
        if not isinstance(reference, dict) or not reference.get("path"):
            continue
        path = _resolve_path(config_path.parent, reference["path"])
        if path is None:
            raise ModuleConfigError(f"Vokabular {vocabulary_id!r} hat keinen Pfad.")
        try:
            load_vocabulary(path, vocabulary_id)
        except VocabularyError as exc:
            raise ModuleConfigError(str(exc)) from exc
        resolved[vocabulary_id] = {"path": str(path)}
    return resolved


def _validate_vocabulary_fields(fields: tuple[ModuleField, ...], references: dict[str, Any]) -> None:
    for field in _walk_fields(fields):
        if field.widget != "vocabulary_select":
            continue
        if not field.vocabulary:
            raise ModuleConfigError(f"vocabulary_select {field.path!r} benoetigt eine Vocabulary-ID.")
        if field.vocabulary not in references:
            raise ModuleConfigError(f"Unbekannte Vocabulary-ID {field.vocabulary!r} fuer Feld {field.path!r}.")


def _sections_and_fields(raw: dict[str, Any], rights: dict[str, dict[str, Any]]) -> tuple[tuple[ModuleSection, ...], tuple[ModuleField, ...]]:
    sections: list[ModuleSection] = []
    fields: list[ModuleField] = []
    for raw_section in raw.get("form", {}).get("sections", []):
        section_fields: list[str] = []
        for raw_field in raw_section.get("fields", []):
            field = _module_field(raw_field, raw_section["id"], rights)
            fields.append(field)
            section_fields.append(field.id)
        for group in raw_section.get("groups", []) or []:
            for raw_field in group.get("fields", []):
                field = _module_field(raw_field, raw_section["id"], rights)
                fields.append(field)
                section_fields.append(field.id)
        sections.append(ModuleSection(
            id=raw_section["id"],
            label=raw_section["label"],
            order=int(raw_section["order"]),
            help=raw_section.get("help"),
            fields=tuple(section_fields),
        ))
    if sections:
        return tuple(sections), tuple(fields)

    legacy_fields = tuple(
        ModuleField(
            id=_field_id(path),
            path=path,
            label=path,
            widget="text",
            section="main",
            order=index,
            view_roles=tuple(rights.get(path, {}).get("view") or rights.get(path, {}).get("read") or ()),
            edit_roles=tuple(rights.get(path, {}).get("edit") or rights.get(path, {}).get("write") or ()),
            presettable=path in set(raw.get("presettable_fields") or ()),
        )
        for index, path in enumerate(raw.get("form_fields") or ())
    )
    return (ModuleSection(id="main", label="Main", order=0, help=None, fields=tuple(field.id for field in legacy_fields)),), legacy_fields


def _enrich_fields_from_schema(fields: tuple[ModuleField, ...], schema: dict[str, Any]) -> tuple[ModuleField, ...]:
    enriched: list[ModuleField] = []
    for field in fields:
        property_schema = _schema_for_path(schema, field.path)
        options = field.options or _schema_options(property_schema)
        enriched.append(replace(
            field,
            required=_schema_requires_path(schema, field.path),
            options=options,
        ))
    return tuple(enriched)


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
    schema = _load_schema(schema_path)

    module_data = raw.get("module") if isinstance(raw.get("module"), dict) else {}
    module_id = _module_id(raw)
    access_key = _access_key(raw)
    signature = raw.get("signature") or raw.get("signature_strategy") or fachkonfiguration.get("signature") or {}
    vocabularies = _vocabulary_references(raw, path)
    field_rights = _field_rights(raw, fachkonfiguration)
    sections, fields = _sections_and_fields(raw, field_rights)
    fields = _enrich_fields_from_schema(fields, schema)
    _validate_vocabulary_fields(fields, vocabularies)

    return ModuleDefinition(
        id=module_id,
        access_key=access_key,
        label=module_data.get("label") or raw.get("label") or fachkonfiguration.get("module_label") or module_id,
        description=module_data.get("description") or raw.get("description"),
        schema_path=schema_path,
        short_label=module_data.get("short_label"),
        category=module_data.get("category"),
        icon=module_data.get("icon"),
        order=int(module_data.get("order", 1000)),
        fachkonfiguration_path=fachkonfiguration_path,
        record_type=module_data.get("record_type") or raw.get("datensatz_typ") or fachkonfiguration.get("datensatz_typ"),
        storage=raw.get("storage") or {},
        id_strategy=raw.get("id") or {},
        signature_strategy=signature,
        sections=sections,
        fields=fields,
        search_config=raw.get("search") or {"fulltext": list(_search_fields(raw))},
        list_config=raw.get("list") or {"columns": [{"label": field, "path": field} for field in _list_fields(raw)]},
        presettable_fields=_presettable_fields(raw, fachkonfiguration),
        field_rights=field_rights,
        vocabularies=vocabularies,
        ui_profiles=raw.get("ui_profiles") or {},
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
    vocabulary_paths: dict[str, str] = {}
    for module in modules:
        for vocabulary_id, reference in module.vocabularies.items():
            path = reference["path"]
            if vocabulary_id in vocabulary_paths and vocabulary_paths[vocabulary_id] != path:
                raise ModuleConfigError(f"Vocabulary-ID {vocabulary_id!r} verweist auf unterschiedliche Dateien.")
            vocabulary_paths[vocabulary_id] = path
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
