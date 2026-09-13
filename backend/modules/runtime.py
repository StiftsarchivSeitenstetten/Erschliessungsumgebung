"""Runtime model derived from declarative module configurations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .access import is_server_managed_field, role_allowed


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

    def can_view(self, role: str) -> bool:
        return role_allowed(role, self.view_roles)

    def can_edit(self, role: str) -> bool:
        return self.can_view(role) and not is_server_managed_field(self.path) and role_allowed(role, self.edit_roles)

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
    schema_path: Path
    fachkonfiguration_path: Path | None
    storage: dict[str, Any]
    id_strategy: dict[str, Any]
    signature_strategy: dict[str, Any]
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
        for field in self.fields:
            if field.path == path:
                return field
        raise KeyError(path)

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

    def descriptor_for_role(self, role: str) -> dict[str, Any]:
        return {
            **self.public_metadata(),
            "record_type": self.record_type,
            "storage": self.storage,
            "id_strategy": self.id_strategy,
            "signature_strategy": self.signature_strategy,
            "sections": [section.descriptor() for section in sorted(self.sections, key=lambda item: item.order)],
            "fields": [
                field.descriptor_for_role(role)
                for field in sorted(self.fields, key=lambda item: (item.section, item.order, item.id))
            ],
            "search": self.search_config,
            "list": self.list_config,
            "vocabularies": self.vocabularies,
            "ui_profiles": self.ui_profiles,
        }
