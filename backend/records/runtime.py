"""Generic record runtime for module-defined canonical records."""

from __future__ import annotations

from copy import deepcopy
from functools import cached_property
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import RefResolver

from ..config import ROOT
from ..modules import ModuleDefinition, get_path_value, path_exists, set_path_value
from ..modules.access import SERVER_MANAGED_FIELDS, is_server_managed_field


TRANSPORT_FIELDS = frozenset({"base_revision", "revision"})
MISSING = object()


class RecordRuntimeError(ValueError):
    pass


class RecordPermissionError(RecordRuntimeError):
    pass


class RecordUnknownFieldError(RecordPermissionError):
    pass


class RecordValidationError(RecordRuntimeError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class RecordRuntime:
    def __init__(self, module: ModuleDefinition) -> None:
        self.module = module
        self.fields_by_path = {field.path: field for field in module.fields}
        self.fields_by_id = {field.id: field for field in module.fields}

    def empty_record(self, role: str | None = None) -> dict[str, Any]:
        record: dict[str, Any] = {}
        for field in self.module.fields:
            if is_server_managed_field(field.path) or (role is not None and not field.can_edit(role)):
                continue
            value = self._empty_value(self._schema_for_path(field.path), field)
            if value is not MISSING:
                set_path_value(record, field.path, value)
        return record

    def filter_for_view(self, record: dict[str, Any], role: str) -> dict[str, Any]:
        visible: dict[str, Any] = {}
        for field in self.module.fields:
            if field.can_view(role) and path_exists(record, field.path):
                set_path_value(visible, field.path, deepcopy(get_path_value(record, field.path)))
        for technical_id in ("id",):
            if technical_id in record:
                visible[technical_id] = deepcopy(record[technical_id])
        return visible

    def filter_for_edit(self, payload: dict[str, Any], role: str) -> dict[str, Any]:
        editable: dict[str, Any] = {}
        for path in self._payload_paths(payload):
            if path in TRANSPORT_FIELDS:
                raise RecordPermissionError(f"Transportmetadatum gehoert nicht in den Datensatz: {path}")
            if is_server_managed_field(path):
                raise RecordPermissionError(f"Feld wird serverseitig verwaltet: {path}")
            field = self.fields_by_path.get(path)
            if field is None:
                raise RecordUnknownFieldError(f"Unbekanntes Feld: {path}")
            if not field.can_edit(role):
                raise RecordPermissionError(f"Keine Schreibberechtigung fuer Feld: {path}")
            set_path_value(editable, path, deepcopy(get_path_value(payload, path)))
        return editable

    def validate(self, record: dict[str, Any]) -> None:
        errors = sorted(self.validator.iter_errors(record), key=lambda error: list(error.path))
        if errors:
            messages = [
                f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
                for error in errors
            ]
            raise RecordValidationError(messages)

    @cached_property
    def schema(self) -> dict[str, Any]:
        return json.loads(self.module.schema_path.read_text(encoding="utf-8"))

    @cached_property
    def core_schema(self) -> dict[str, Any]:
        core_schema_path = ROOT / "schemas" / "core-datatypes.schema.json"
        return json.loads(core_schema_path.read_text(encoding="utf-8"))

    @cached_property
    def validator(self):
        core_schema_path = ROOT / "schemas" / "core-datatypes.schema.json"
        store = {
            self.core_schema.get("$id", str(core_schema_path)): self.core_schema,
            str(core_schema_path): self.core_schema,
        }
        resolver = RefResolver.from_schema(self.schema, store=store)
        return jsonschema.Draft202012Validator(self.schema, resolver=resolver)

    def _schema_for_path(self, path: str) -> dict[str, Any]:
        schema = self.schema
        for part in path.split("."):
            schema = self._resolve_schema(schema)
            schema = schema.get("properties", {}).get(part, {})
        return self._resolve_schema(schema)

    def _resolve_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        reference = schema.get("$ref")
        if not reference:
            return schema
        fragment = reference.split("#", 1)[1] if "#" in reference else ""
        documents = [self.core_schema] if reference.startswith(self.core_schema.get("$id", "<no-id>")) else [self.schema, self.core_schema]
        for document in documents:
            resolved: Any = document
            try:
                for part in fragment.removeprefix("/").split("/") if fragment else ():
                    resolved = resolved[part.replace("~1", "/").replace("~0", "~")]
            except (KeyError, TypeError):
                continue
            return resolved
        return schema

    def _empty_value(self, schema: dict[str, Any], field: Any | None = None) -> Any:
        schema = self._resolve_schema(schema)
        if "default" in schema:
            return deepcopy(schema["default"])
        if "const" in schema:
            return deepcopy(schema["const"])
        types = schema.get("type", [])
        types = [types] if isinstance(types, str) else list(types)
        if "array" in types:
            return []
        if "boolean" in types:
            return False
        if "object" in types or "properties" in schema:
            value = {}
            for key in schema.get("required", []):
                child = self._empty_value(schema.get("properties", {}).get(key, {}))
                if child is not MISSING:
                    value[key] = child
            if field and field.options:
                selected = deepcopy(field.options[0]["value"])
                if field.widget == "vocabulary_select":
                    value["id"] = selected
                elif field.widget == "select" and "code" in schema.get("properties", {}):
                    value["code"] = selected
            return value
        if field and field.options:
            return deepcopy(field.options[0]["value"])
        if "null" in types:
            return None
        if schema.get("enum"):
            return deepcopy(schema["enum"][0])
        if "string" in types:
            return ""
        return MISSING

    def prepare_create(self, payload: dict[str, Any], user: Any, server_values: dict[str, Any] | None = None) -> dict[str, Any]:
        record = self.filter_for_edit(payload, user.role)
        for path, value in (server_values or {}).items():
            set_path_value(record, path, deepcopy(value))
        self._apply_create_metadata(record, user)
        self.validate(record)
        return record

    def prepare_update(self, existing: dict[str, Any], payload: dict[str, Any], user: Any) -> dict[str, Any]:
        updated = deepcopy(existing)
        changes = self.filter_for_edit(payload, user.role)
        for path in self._payload_paths(changes):
            set_path_value(updated, path, deepcopy(get_path_value(changes, path)))
        self._apply_update_metadata(updated, user)
        self.validate(updated)
        return updated

    def _apply_create_metadata(self, record: dict[str, Any], user: Any) -> None:
        now = utc_iso()
        self._set_if_schema_allows(record, "technik.erstellt_am", now)
        self._set_if_schema_allows(record, "technik.erstellt_von", user.username)
        self._set_if_schema_allows(record, "technik.geaendert_am", None)
        self._set_if_schema_allows(record, "technik.geaendert_von", None)

    def _apply_update_metadata(self, record: dict[str, Any], user: Any) -> None:
        now = utc_iso()
        self._set_if_schema_allows(record, "technik.geaendert_am", now)
        self._set_if_schema_allows(record, "technik.geaendert_von", user.username)

    def _set_if_schema_allows(self, record: dict[str, Any], path: str, value: Any) -> None:
        if path in SERVER_MANAGED_FIELDS:
            set_path_value(record, path, value)

    def _payload_paths(self, payload: dict[str, Any]) -> list[str]:
        paths: list[str] = []

        def walk(value: Any, prefix: str) -> None:
            if prefix in self.fields_by_path or prefix in SERVER_MANAGED_FIELDS or prefix in TRANSPORT_FIELDS:
                paths.append(prefix)
                return
            if isinstance(value, dict):
                if not value and prefix:
                    paths.append(prefix)
                for key, child in value.items():
                    walk(child, f"{prefix}.{key}" if prefix else str(key))
                return
            paths.append(prefix)

        walk(payload, "")
        return [path for path in paths if path]
