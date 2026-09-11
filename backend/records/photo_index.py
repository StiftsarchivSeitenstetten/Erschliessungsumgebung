"""Derived search index for photo records.

The Markdown/YAML records remain canonical. This module only builds and reads a
reproducible index that can later grow with additional derived search fields.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable

import yaml

from scripts.foto_core import extract_frontmatter

from ..github.errors import RepositoryNotFoundError
from ..github.repository import DataRepository


INDEX_PATH = "indexes/fotos.json"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PhotoIndex:
    records: list[dict[str, Any]]

    def by_id(self, record_id: str) -> dict[str, Any] | None:
        return next((entry for entry in self.records if entry.get("id") == record_id), None)

    def by_signature(self, signature: str) -> dict[str, Any] | None:
        return next((entry for entry in self.records if entry.get("signatur") == signature), None)

    def signature_family(self, base_signature: str) -> list[dict[str, Any]]:
        return [
            entry
            for entry in self.records
            if entry.get("signatur") == base_signature
            or str(entry.get("signatur", "")).startswith(base_signature)
        ]


def record_path(record_id: str) -> str:
    return f"data/fotos/{record_id}.md"


def index_entry(record: dict[str, Any]) -> dict[str, Any]:
    signatur = record.get("signatur", {})
    return {
        "id": record["id"],
        "signatur": signatur["anzeige"],
        "format": signatur["format"],
        "nummer": int(signatur["nummer"]),
        "zusatz": signatur.get("zusatz"),
    }


def build_photo_index(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    entries = [index_entry(record) for record in records]
    entries.sort(key=lambda entry: entry["id"])
    return {"schema_version": SCHEMA_VERSION, "records": entries}


def parse_photo_index(data: dict[str, Any]) -> PhotoIndex:
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Fotoindex hat eine nicht unterstuetzte schema_version.")
    records = data.get("records")
    if not isinstance(records, list):
        raise ValueError("Fotoindex enthaelt keine records-Liste.")
    return PhotoIndex(records=records)


def read_photo_index(repository: DataRepository) -> PhotoIndex:
    try:
        content = repository.read_file(INDEX_PATH).content
    except RepositoryNotFoundError:
        return PhotoIndex(records=[])
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("Fotoindex ist kein JSON-Objekt.")
    return parse_photo_index(parsed)


def dump_photo_index(index: dict[str, Any] | PhotoIndex) -> str:
    data = {"schema_version": SCHEMA_VERSION, "records": index.records} if isinstance(index, PhotoIndex) else index
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def append_index_record(index: PhotoIndex, record: dict[str, Any]) -> dict[str, Any]:
    entries = list(index.records)
    entries.append(index_entry(record))
    return build_photo_index_from_entries(entries)


def update_index_record(index: PhotoIndex, record: dict[str, Any]) -> dict[str, Any]:
    entry = index_entry(record)
    entries = [existing for existing in index.records if existing.get("id") != record["id"]]
    entries.append(entry)
    return build_photo_index_from_entries(entries)


def build_photo_index_from_entries(entries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    normalized = []
    for entry in entries:
        normalized.append({
            "id": entry["id"],
            "signatur": entry["signatur"],
            "format": entry["format"],
            "nummer": int(entry["nummer"]),
            "zusatz": entry.get("zusatz"),
        })
    normalized.sort(key=lambda entry: entry["id"])
    return {"schema_version": SCHEMA_VERSION, "records": normalized}


def index_entry_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return index_entry(before) != index_entry(after)


def load_yaml_record(path: Path) -> dict[str, Any]:
    yaml_text, _ = extract_frontmatter(path.read_text(encoding="utf-8"))
    parsed = yaml.safe_load(yaml_text)
    if not isinstance(parsed, dict):
        raise ValueError(f"{path}: YAML-Frontmatter ist kein Mapping.")
    return parsed


def build_photo_index_from_directory(data_dir: Path) -> dict[str, Any]:
    records = [load_yaml_record(path) for path in sorted(data_dir.glob("foto-*.md"))]
    return build_photo_index(records)


def validate_photo_index(data_dir: Path, index: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    parsed = parse_photo_index(index)
    entries = parsed.records
    ids = [entry.get("id") for entry in entries]
    signatures = [entry.get("signatur") for entry in entries]
    for value, label in ((ids, "technische ID"), (signatures, "Signatur")):
        duplicates = [item for item, count in Counter(value).items() if count > 1]
        if duplicates:
            errors.append(f"Doppelte {label}: {duplicates[:10]}")
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        suffix = entry.get("zusatz") or ""
        base = str(entry.get("signatur", ""))
        if suffix and base.endswith(suffix):
            base = base[: -len(suffix)]
        by_family[base].append(entry)
        record_id = entry.get("id")
        path = data_dir / f"{record_id}.md"
        if not path.exists():
            errors.append(f"Indexeintrag ohne Datei: {record_id}")
            continue
        record = load_yaml_record(path)
        expected = index_entry(record)
        if entry != expected:
            errors.append(f"Indexeintrag stimmt nicht mit YAML ueberein: {record_id}")
    if "foto-008117" in ids:
        errors.append("Zurueckgestellter Konfliktdatensatz foto-008117 darf nicht im Fotoindex stehen.")
    return errors
