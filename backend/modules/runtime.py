"""Runtime model derived from declarative module configurations."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from copy import deepcopy
from pathlib import Path
from typing import Any

from .access import is_server_managed_field, role_allowed
from .paths import get_path_value, path_exists, set_path_value


@dataclass(frozen=True)
class ModuleField:
    id: str
    path: str
    label: str
    widget: str
    section: str
    order: int
    help: str | None = None
    placeholder: str | None = None
    presettable: bool = False
    view_roles: tuple[str, ...] = ()
    edit_roles: tuple[str, ...] = ()
    vocabulary: str | None = None
    item_fields: tuple["ModuleField", ...] = ()
    required: bool = False
    options: tuple[dict[str, Any], ...] = ()
    schema_default: Any = None
    has_default: bool = False
    exclusive_minimum: float | None = None
    schema_const: Any = None
    has_const: bool = False
    repeater_policies: dict[str, str] = dataclass_field(default_factory=dict)

    def can_view(self, role: str) -> bool:
        return role_allowed(role, self.view_roles)

    def can_edit(self, role: str) -> bool:
        return self.can_view(role) and not is_server_managed_field(self.path) and role_allowed(role, self.edit_roles)

    def visible_value(self, value: Any, role: str) -> Any:
        if self.widget != "repeater" or not isinstance(value, list) or not (self.has_hidden_items(role) or self.has_protected_items(role)):
            return deepcopy(value)
        visible = []
        for item in value:
            if isinstance(item, list):
                visible.append(self.visible_value(item, role))
                continue
            if not isinstance(item, dict):
                visible.append(deepcopy(item))
                continue
            result: dict[str, Any] = {}
            for field in self.item_fields:
                if field.can_view(role) and path_exists(item, field.path):
                    set_path_value(result, field.path, field.visible_value(get_path_value(item, field.path), role))
            visible.append(result)
        return visible

    def has_protected_items(self, role: str) -> bool:
        return self.repeater_policies.get(role) == "constants" or any(not field.can_edit(role) or field.has_protected_items(role) for field in self.item_fields)

    def has_hidden_items(self, role: str) -> bool:
        return any(not field.can_view(role) or field.has_hidden_items(role) for field in self.item_fields)

    def descriptor_for_role(self, role: str) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "label": self.label,
            "widget": self.widget,
            "section": self.section,
            "order": self.order,
            "help": self.help,
            "placeholder": self.placeholder,
            "presettable": self.presettable,
            "visible": self.can_view(role),
            "editable": self.can_edit(role),
            "vocabulary": self.vocabulary,
            "item_fields": [field.descriptor_for_role(role) for field in self.item_fields],
            "required": self.required,
            "options": list(self.options),
            **({"const": deepcopy(self.schema_const)} if self.has_const and self.can_view(role) else {}),
            **({"repeater_policy": self.repeater_policies.get(role)} if self.widget == "repeater" and self.can_edit(role) else {}),
            **({"default": self.visible_value(self.schema_default, role)} if self.has_default and self.can_view(role) else {}),
            **({"exclusiveMinimum": self.exclusive_minimum} if self.exclusive_minimum is not None else {}),
        }


@dataclass(frozen=True)
class ModuleSection:
    id: str
    label: str
    order: int
    help: str | None
    fields: tuple[str, ...]

    def descriptor(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "order": self.order,
            "help": self.help,
            "fields": list(self.fields),
        }


@dataclass(frozen=True)
class ModuleDefinition:
    id: str
    access_key: str
    label: str
    description: str | None
    record_type: str | None
    short_label: str | None
    category: str | None
    icon: str | None
    entrypoint: str
    order: int
    schema_path: Path
    fachkonfiguration_path: Path | None
    storage: dict[str, Any]
    id_strategy: dict[str, Any]
    signature_strategy: dict[str, Any]
    create_strategy: dict[str, Any]
    sections: tuple[ModuleSection, ...]
    fields: tuple[ModuleField, ...]
    search_config: dict[str, Any]
    list_config: dict[str, Any]
    presettable_fields: tuple[str, ...]
    field_rights: dict[str, dict[str, Any]]
    vocabularies: dict[str, Any]
    ui_profiles: dict[str, Any]

    @property
    def datensatz_typ(self) -> str | None:
        return self.record_type

    @property
    def form_fields(self) -> tuple[str, ...]:
        return tuple(field.path for field in self.fields)

    @property
    def search_fields(self) -> tuple[str, ...]:
        return tuple(self.search_config.get("fulltext") or ())

    @property
    def list_fields(self) -> tuple[str, ...]:
        return tuple(column["path"] for column in self.list_config.get("columns", []))

    def get_field(self, field_id: str) -> ModuleField:
        for field in self.fields:
            if field.id == field_id:
                return field
        raise KeyError(field_id)

    def get_field_by_path(self, path: str) -> ModuleField:
        for full_path, field in self._field_paths():
            if full_path.replace("[]", "") == path.replace("[]", ""):
                return field
        raise KeyError(path)

    def _field_paths(self):
        def walk(fields, prefix=""):
            for field in fields:
                full = f"{prefix}.{field.path}" if prefix else field.path
                yield full, field
                yield from walk(field.item_fields, full + "[]")
        return walk(self.fields)

    def field_for_path(self, path: str) -> ModuleField | None:
        normalized = path.replace("[]", "")
        candidates = [(full, field) for full, field in self._field_paths()
            if normalized == full.replace("[]", "") or normalized.startswith(full.replace("[]", "") + ".")]
        return max(candidates, key=lambda item: len(item[0]))[1] if candidates else None

    def can_view_field(self, field: str, role: str) -> bool:
        return self._resolve_field(field).can_view(role)

    def can_edit_field(self, field: str, role: str) -> bool:
        return self._resolve_field(field).can_edit(role)

    def _resolve_field(self, field: str) -> ModuleField:
        try:
            return self.get_field(field)
        except KeyError:
            return self.get_field_by_path(field)

    def public_metadata(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "module": self.access_key,
            "label": self.label,
            "description": self.description,
            "datensatz_typ": self.record_type,
            "schema": str(self.schema_path),
            "form_fields": list(self.form_fields),
            "search_fields": list(self.search_fields),
            "list_fields": list(self.list_fields),
        }

    def catalog_metadata(self) -> dict[str, Any]:
        return {
            "id": self.access_key,
            "module_id": self.id,
            "label": self.short_label or self.label,
            "description": self.description,
            "category": self.category,
            "icon": self.icon,
            "entrypoint": self.entrypoint,
            "order": self.order,
        }

    def descriptor_for_role(self, role: str) -> dict[str, Any]:
        def visible(path):
            if path == "id":
                return True
            field = self.field_for_path(path)
            return field is not None and field.can_view(role)

        search = {**self.search_config}
        for key in ("fulltext", "lookup"):
            search[key] = [path for path in search.get(key, []) if visible(path)]
        search["filters"] = [field for field in search.get("filters", []) if visible(field["path"])]
        listing = {**self.list_config, "columns": [column for column in self.list_config.get("columns", []) if visible(column["path"])]}
        return {
            **self.public_metadata(),
            "record_type": self.record_type,
            "storage": self.storage,
            "id_strategy": self.id_strategy,
            "signature_strategy": self.signature_strategy,
            "create": {**self.create_strategy, **({"server_values": {
                path: self.field_for_path(path).visible_value(value, role)
                for path, value in self.create_strategy["server_values"].items()
                if self.field_for_path(path) is not None and visible(path)
            }} if "server_values" in self.create_strategy else {})},
            "sections": [section.descriptor() for section in sorted(self.sections, key=lambda item: item.order)],
            "fields": [
                field.descriptor_for_role(role)
                for field in sorted(self.fields, key=lambda item: (item.section, item.order, item.id))
            ],
            "search": search,
            "list": listing,
            "vocabularies": sorted(self.vocabularies),
            "ui_profiles": self.ui_profiles,
        }
