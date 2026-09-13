"""Generic record runtime for module-defined canonical records."""

from __future__ import annotations

from copy import deepcopy
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

    def empty_record(self) -> dict[str, Any]:
        return {}

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
        schema = json.loads(self.module.schema_path.read_text(encoding="utf-8"))
        core_schema_path = ROOT / "schemas" / "core-datatypes.schema.json"
        core_schema = json.loads(core_schema_path.read_text(encoding="utf-8"))
        store = {
            core_schema.get("$id", str(core_schema_path)): core_schema,
            str(core_schema_path): core_schema,
        }
        resolver = RefResolver.from_schema(schema, store=store)
        validator = jsonschema.Draft202012Validator(schema, resolver=resolver)
        errors = sorted(validator.iter_errors(record), key=lambda error: list(error.path))
        if errors:
            messages = [
                f"{'.'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
                for error in errors
            ]
            raise RecordValidationError(messages)

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
