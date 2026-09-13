"""Generic read-only record loading for module-backed repositories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

from ..github.repository import DataRepository, RepositoryFile
from ..modules import ModuleDefinition, get_path_value, path_exists
from .runtime import RecordRuntime


@dataclass(frozen=True)
class GenericStoredRecord:
    record_id: str
    data: dict[str, Any]
    revision: str
    path: str


def record_path(module: ModuleDefinition, record_id: str) -> str:
    data_dir = module.storage["data_dir"].rstrip("/")
    extension = module.storage.get("filename", {}).get("extension", ".md")
    return f"{data_dir}/{record_id}{extension}"


def parse_record_file(file: RepositoryFile) -> GenericStoredRecord:
    data = parse_record_content(file.content)
    return GenericStoredRecord(record_id=str(data.get("id") or ""), data=data, revision=file.revision, path=file.path)


def parse_record_content(content: str) -> dict[str, Any]:
    if content.startswith("---\n"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            parsed = yaml.safe_load(parts[1]) or {}
        else:
            parsed = yaml.safe_load(content) or {}
    else:
        parsed = yaml.safe_load(content) or {}
    if not isinstance(parsed, dict):
        raise ValueError("Datensatz ist kein Mapping.")
    return parsed


def read_generic_record(repository: DataRepository, module: ModuleDefinition, record_id: str) -> GenericStoredRecord:
    return parse_record_file(repository.read_file(record_path(module, record_id)))


def list_generic_records(repository: DataRepository, module: ModuleDefinition) -> list[GenericStoredRecord]:
    data_dir = module.storage["data_dir"]
    extension = module.storage.get("filename", {}).get("extension", ".md")
    return [
        parse_record_file(file)
        for file in repository.list_directory(data_dir)
        if file.path.endswith(extension)
    ]


def list_values_for_role(record: dict[str, Any], module: ModuleDefinition, role: str) -> dict[str, Any]:
    runtime = RecordRuntime(module)
    values: dict[str, Any] = {}
    for column in module.list_config.get("columns", []):
        path = column["path"]
        if not is_path_visible(module, path, role):
            continue
        if path_exists(record, path):
            values[path] = get_path_value(record, path)
    return values


def is_path_visible(module: ModuleDefinition, path: str, role: str) -> bool:
    try:
        return module.can_view_field(path, role)
    except KeyError:
        rights = module.field_rights.get(path)
        if rights is None:
            return False
        return role in set(rights.get("view") or rights.get("read") or [])
