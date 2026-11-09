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
from ..github.errors import RepositoryNotFoundError
from ..github.repository import DataRepository
from ..modules import ModuleDefinition, get_path_value, path_exists, set_path_value
from ..modules.access import SERVER_MANAGED_FIELDS, is_server_managed_field
from ..modules.repeater import repeater_plan, UnsafeRepeaterError
from ..vocabularies import VocabularyTermNotFound, load_vocabulary, read_repository_vocabulary


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
    def __init__(self, module: ModuleDefinition, repository: DataRepository | None = None) -> None:
        self.module = module
        self.repository = repository
        self.fields_by_path = {field.path: field for field in module.fields}
        self.fields_by_id = {field.id: field for field in module.fields}

    def empty_record(self, role: str | None = None) -> dict[str, Any]:
        record: dict[str, Any] = {}
        fixed = self.module.create_strategy.get("server_values") or {}
        signature_root = self.module.signature_strategy.get("output_path", "signatur")
        allocated = {"id", f"{signature_root}.nummer", f"{signature_root}.anzeige"}
        for field in self.module.fields:
            if is_server_managed_field(field.path) or field.path in allocated or (role is not None and not field.can_view(role)):
                continue
            schema = self._schema_for_path(field.path)
            if role is not None and not field.can_edit(role):
                # Do not invent text, enum choices or identities for readonly fields.
                if field.path not in fixed and "default" not in schema and "const" not in schema:
                    continue
                value = deepcopy(fixed.get(field.path, schema.get("default", schema.get("const"))))
            elif field.widget == "vocabulary_select" and field.vocabulary:
                vocabulary = self._vocabulary(field.vocabulary)
                active = vocabulary.active_terms()
                value = {"id": active[0].id, "vocabulary_id": vocabulary.id} if active else MISSING
            else:
                value = self._empty_value(schema, field)
            if value is not MISSING:
                set_path_value(record, field.path, field.visible_value(value, role) if role is not None else value)
        return record

    def filter_for_view(self, record: dict[str, Any], role: str) -> dict[str, Any]:
        visible: dict[str, Any] = {}
        for field in self.module.fields:
            if field.can_view(role) and path_exists(record, field.path):
                set_path_value(visible, field.path, field.visible_value(get_path_value(record, field.path), role))
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
            value = get_path_value(payload, path)
            if field.widget == "repeater" and isinstance(value, list):
                value = self._filter_repeater_edit(field, value, role, path)
            set_path_value(editable, path, deepcopy(value))
        return editable

    def _filter_repeater_edit(self, field, items, role, prefix):
        if not field.has_protected_items(role):
            return deepcopy(items)
        fields = {child.path: child for child in field.item_fields}
        result = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                result.append(deepcopy(item))  # Structural errors remain schema errors.
                continue
            filtered = {}
            for path in self._payload_paths(item, fields):
                child = fields.get(path)
                full_path = f"{prefix}.{index}.{path}"
                if child is None:
                    raise RecordUnknownFieldError(f"Unbekanntes Feld: {full_path}")
                if not child.can_edit(role):
                    raise RecordPermissionError(f"Keine Schreibberechtigung fuer Feld: {full_path}")
                value = get_path_value(item, path)
                if child.widget == "repeater" and isinstance(value, list):
                    value = self._filter_repeater_edit(child, value, role, full_path)
                set_path_value(filtered, path, deepcopy(value))
            result.append(filtered)
        return result

    def _repeater_plan(self, field, schema, role):
        try:
            return repeater_plan(field, schema, role, self._resolve_schema)
        except UnsafeRepeaterError as exc:
            raise RecordPermissionError(str(exc)) from exc

    def _check_repeater_baseline(self, field, items, schema, role, prefix=None):
        plan = self._repeater_plan(field, schema, role)
        prefix = prefix or field.path
        if not plan.mixed or not isinstance(items, list):
            return
        item_schema = self._resolve_schema(schema.get("items", {}))
        for index, item in enumerate(items):
            path = f"{prefix}.{index}"
            if not isinstance(item, dict):
                raise RecordPermissionError(f"{path}: Geschützte Bestandszeile ist kein Objekt.")
            for key, value in plan.constants.items():
                if not path_exists(item, key) or not self._constant_equal(get_path_value(item, key), value):
                    raise RecordPermissionError(f"{path}.{key}: Geschützter Bestandswert weicht vom erforderlichen Schema-const ab.")
            # Reject unknown historical data before replacing even deleted rows.
            def check_keys(value, node, relative=""):
                if relative in {child.path for child in field.item_fields}:
                    return
                node = self._resolve_schema(node)
                if not isinstance(value, dict):
                    return
                for key, child_value in value.items():
                    child_path = f"{relative}.{key}" if relative else key
                    if key not in node.get("properties", {}):
                        raise RecordPermissionError(f"{path}.{child_path}: Nicht deklarierte Bestandsinformation kann nicht sicher ersetzt werden.")
                    check_keys(child_value, node["properties"][key], child_path)
            check_keys(item, item_schema)
            for child in field.item_fields:
                if child.path in plan.children and path_exists(item, child.path):
                    self._check_repeater_baseline(child, get_path_value(item, child.path),
                        self._schema_at_path(item_schema, child.path), role, f"{path}.{child.path}")

    @staticmethod
    def _constant_equal(left, right):
        # JSON equality must not equate booleans and numbers (Python otherwise does).
        return jsonschema.Draft202012Validator({"const": right}).is_valid(left)

    def _merge_repeater(self, field, incoming, existing, schema, role):
        if field.widget != "repeater" or not field.can_edit(role):
            return deepcopy(incoming)
        plan = self._repeater_plan(field, schema, role)
        self._check_repeater_baseline(field, existing, schema, role)
        if not isinstance(incoming, list) or not plan.mixed:
            return deepcopy(incoming)
        item_schema = self._resolve_schema(schema.get("items", {}))
        result = deepcopy(incoming)
        for item in result:
            if not isinstance(item, dict):
                continue  # Structural errors remain schema errors.
            for path, value in plan.constants.items():
                set_path_value(item, path, deepcopy(value))
            for child in field.item_fields:
                if child.path in plan.children and path_exists(item, child.path):
                    set_path_value(item, child.path, self._merge_repeater(child,
                        get_path_value(item, child.path), None,
                        self._schema_at_path(item_schema, child.path), role))
        return result

    def validate(self, record: dict[str, Any]) -> None:
        errors = sorted(self.validator.iter_errors(record), key=lambda error: list(error.path))
        if errors:
            messages = []
            for error in errors:
                path = ".".join(str(part) for part in error.path) or "<root>"
                message = error.message
                if self.module.create_strategy.get("workflow"):
                    field = self.module.field_for_path(".".join(str(part) for part in error.path if not isinstance(part, int)))
                    label = field.label if field else path
                    message = {
                        "pattern": "Bitte einen nichtleeren Text eingeben.",
                        "contains": "Ein erforderlicher Listeneintrag fehlt.",
                        "type": "Bitte einen gültigen Wert eingeben; Maßwerte müssen Zahlen sein.",
                        "exclusiveMinimum": "Der Wert muss größer als 0 sein.",
                        "required": "Pflichtangaben fehlen: " + ", ".join(key for key in error.validator_value if key not in error.instance) if error.validator == "required" else "",
                    }.get(error.validator, message)
                    path = f"{label} ({path})"
                messages.append(f"{path}: {message}")
            raise RecordValidationError(messages)

    def validate_vocabulary_references(self, record: dict[str, Any]) -> None:
        errors: list[str] = []

        def validate_field(field, value, path: str) -> None:
            if field.widget == "vocabulary_select" and value is not None:
                if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"]:
                    errors.append(f"{path}: Vocabulary-Wert muss ein term_ref mit stabiler ID sein.")
                    return
                if value.get("vocabulary_id") not in (None, field.vocabulary):
                    errors.append(f"{path}: Vocabulary-ID passt nicht zum konfigurierten Vokabular.")
                    return
                vocabulary = self._vocabulary(field.vocabulary)
                try:
                    vocabulary.resolve(value["id"])
                except VocabularyTermNotFound:
                    errors.append(f"{path}: Unbekannte Term-ID {value['id']!r}.")
            if field.widget == "repeater" and isinstance(value, list):
                for index, item in enumerate(value):
                    if not isinstance(item, dict):
                        continue
                    for item_field in field.item_fields:
                        if path_exists(item, item_field.path):
                            validate_field(item_field, get_path_value(item, item_field.path), f"{path}.{index}.{item_field.path}")

        for field in self.module.fields:
            if path_exists(record, field.path):
                validate_field(field, get_path_value(record, field.path), field.path)
        if errors:
            raise RecordValidationError(errors)

    def _vocabulary(self, vocabulary_id: str):
        reference = self.module.vocabularies[vocabulary_id]
        if self.repository is not None:
            try:
                return read_repository_vocabulary(
                    self.repository, reference["repository_path"], vocabulary_id,
                ).vocabulary
            except RepositoryNotFoundError:
                pass
        return load_vocabulary(reference["path"], vocabulary_id)

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
        return self._schema_at_path(self.schema, path)

    def _schema_at_path(self, schema: dict[str, Any], path: str) -> dict[str, Any]:
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

    def apply_action(self, record, action, user, existing=None):
        workflow = self.module.create_strategy.get("workflow")
        if not workflow:
            if action is not None:
                raise RecordValidationError(["Aktion fuer dieses Modul nicht verfuegbar."])
            return
        if user.role not in workflow["roles"]:
            raise RecordPermissionError("Keine Berechtigung fuer Speicheraktionen.")
        path = workflow["status_path"]
        current = get_path_value(existing or {}, path, workflow["draft_status"])
        completed = workflow["completed_status"]
        targets = {"draft": workflow["draft_status"], "complete": completed, "save": completed}
        if action not in targets or (current == completed and action != "save") or (current != completed and action == "save"):
            raise RecordValidationError(["Speicheraktion ist fuer diesen Erfassungsstatus nicht erlaubt."])
        set_path_value(record, path, targets[action])

    def prepare_create(self, payload: dict[str, Any], user: Any, server_values: dict[str, Any] | None = None, action: str | None = None) -> dict[str, Any]:
        record = self.filter_for_edit(payload, user.role)
        for field in self.module.fields:
            if path_exists(record, field.path):
                set_path_value(record, field.path, self._merge_repeater(field, get_path_value(record, field.path), None, self._schema_for_path(field.path), user.role))
        for path, value in (server_values or {}).items():
            set_path_value(record, path, deepcopy(value))
        self._apply_create_metadata(record, user)
        self.apply_action(record, action, user)
        self.validate(record)
        self.validate_vocabulary_references(record)
        return record

    def prepare_update(self, existing: dict[str, Any], payload: dict[str, Any], user: Any, action: str | None = None) -> dict[str, Any]:
        for field in self.module.fields:
            if field.widget == "repeater" and field.can_edit(user.role):
                self._check_repeater_baseline(field, get_path_value(existing, field.path, None),
                    self._schema_for_path(field.path), user.role)
        updated = deepcopy(existing)
        changes = self.filter_for_edit(payload, user.role)
        for path in self._payload_paths(changes):
            field = self.fields_by_path[path]
            value = self._merge_repeater(field, get_path_value(changes, path), get_path_value(existing, path, None), self._schema_for_path(path), user.role)
            set_path_value(updated, path, value)
        self._apply_update_metadata(updated, user)
        self.apply_action(updated, action, user, existing)
        self.validate(updated)
        self.validate_vocabulary_references(updated)
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

    def _payload_paths(self, payload: dict[str, Any], fields_by_path=None) -> list[str]:
        paths: list[str] = []
        fields = self.fields_by_path if fields_by_path is None else fields_by_path

        def walk(value: Any, prefix: str) -> None:
            if prefix in fields or prefix in SERVER_MANAGED_FIELDS or prefix in TRANSPORT_FIELDS:
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
