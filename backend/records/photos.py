"""Server-side photo record persistence and allocation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any

import yaml

from scripts.foto_core import (
    build_signature,
    extract_frontmatter,
    load_config,
    render_photo_markdown,
    validate_record,
    validate_record_schema,
)

from ..github.errors import RepositoryConflictError, RepositoryNotFoundError
from ..github.repository import DataRepository, RepositoryFile
from ..models import User
from ..permissions import can_edit_record


DATA_DIR = "data/fotos"
STATE_PATH = "state/foto-papierabzuege.json"
MAX_RETRIES = 5


class RecordValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class RecordPermissionError(PermissionError):
    pass


class RecordRevisionConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class StoredRecord:
    data: dict[str, Any]
    body: str
    revision: str


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_markdown_file(file: RepositoryFile) -> StoredRecord:
    yaml_text, body = extract_frontmatter(file.content)
    data = yaml.safe_load(yaml_text)
    if not isinstance(data, dict):
        raise RecordValidationError(["YAML-Frontmatter ist kein Mapping."])
    return StoredRecord(data=data, body=body, revision=file.revision)


def record_path(record_id: str) -> str:
    return f"{DATA_DIR}/{record_id}.md"


def list_photo_records(repository: DataRepository) -> list[StoredRecord]:
    return [parse_markdown_file(file) for file in repository.list_directory(DATA_DIR)]


def read_photo_record(repository: DataRepository, record_id: str) -> StoredRecord:
    return parse_markdown_file(repository.read_file(record_path(record_id)))


def bootstrap_state(repository: DataRepository) -> dict[str, Any]:
    config = load_config()
    formats = {format_code: 1 for format_code in config["signature"]["formats"]}
    max_id = 0
    try:
        records = list_photo_records(repository)
    except RepositoryNotFoundError:
        records = []
    for stored in records:
        record = stored.data
        record_id = str(record.get("id", ""))
        if record_id.startswith("foto-"):
            try:
                max_id = max(max_id, int(record_id.removeprefix("foto-")))
            except ValueError:
                pass
        signatur = record.get("signatur", {})
        format_code = signatur.get("format")
        number = signatur.get("nummer")
        if format_code in formats and isinstance(number, int):
            formats[format_code] = max(formats[format_code], number + 1)
    return {"next_id": max_id + 1, "formats": formats}


def read_state(repository: DataRepository) -> dict[str, Any]:
    try:
        return json.loads(repository.read_file(STATE_PATH).content)
    except RepositoryNotFoundError:
        return bootstrap_state(repository)


def dump_state(state: dict[str, Any]) -> str:
    return json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def canonical_erschliessung(values: dict[str, Any]) -> dict[str, Any]:
    return {
        "titel": values.get("titel"),
        "beschriftung": values.get("beschriftung"),
        "beschreibung": values.get("beschreibung"),
        "dargestellte_personen": values.get("dargestellte_personen") or [],
        "herkunft": values.get("herkunft"),
        "sammler": values.get("sammler"),
        "fotograf": values.get("fotograf"),
        "rechteinhaber": values.get("rechteinhaber"),
        "orte": values.get("orte") or [],
        "schlagworte": values.get("schlagworte") or [],
        "altsignaturen": values.get("altsignaturen") or [],
        "interne_bemerkung": values.get("interne_bemerkung"),
    }


def build_new_record(payload: dict[str, Any], user: User, state: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    format_code = str(payload.get("format", "")).upper()
    if format_code not in config["signature"]["formats"]:
        raise RecordValidationError(["format ist unzulaessig."])
    record_id = f"foto-{int(state['next_id']):06d}"
    number = int(state["formats"][format_code])
    now = utc_iso()
    return {
        "schema_version": 1,
        "id": record_id,
        "datensatz_typ": config["datensatz_typ"],
        "modul": config["module_id"],
        "signatur": build_signature(format_code, number, config, status="vergeben"),
        "erschliessung": canonical_erschliessung(payload.get("erschliessung") or {}),
        "korrespondenzstueck": bool(payload.get("korrespondenzstueck", False)),
        "datierung": payload.get("datierung") or {"jahr": None, "monat": None, "tag": None},
        "redaktion": {"stufe": "ehrenamtlich"},
        "bearbeitung": {"status": config["defaults"]["bearbeitung_status"]},
        "publikation": {"status": config["defaults"]["publikation_status"]},
        "technik": {
            "quelle": "webapp",
            "erstellt_am": now,
            "erstellt_von": user.username,
            "geaendert_am": None,
            "geaendert_von": None,
        },
    }


def update_record(existing: dict[str, Any], payload: dict[str, Any], user: User) -> dict[str, Any]:
    updated = dict(existing)
    updated["erschliessung"] = canonical_erschliessung(payload.get("erschliessung") or existing.get("erschliessung", {}))
    updated["korrespondenzstueck"] = bool(payload.get("korrespondenzstueck", existing.get("korrespondenzstueck", False)))
    updated["datierung"] = payload.get("datierung") or existing.get("datierung") or {"jahr": None, "monat": None, "tag": None}
    technik = dict(existing.get("technik", {}))
    technik.setdefault("quelle", "webapp")
    technik.setdefault("erstellt_am", None)
    technik.setdefault("erstellt_von", None)
    technik["geaendert_am"] = utc_iso()
    technik["geaendert_von"] = user.username
    updated["technik"] = technik
    return updated


def validate_canonical_record(record: dict[str, Any]) -> None:
    errors = validate_record_schema(record)
    errors.extend(validate_record(record))
    if errors:
        raise RecordValidationError(errors)


def create_photo_record(repository: DataRepository, payload: dict[str, Any], user: User) -> StoredRecord:
    last_conflict: RepositoryConflictError | None = None
    for _ in range(MAX_RETRIES):
        head = repository.get_branch_head()
        state = read_state(repository)
        record = build_new_record(payload, user, state)
        validate_canonical_record(record)
        state["next_id"] = int(state["next_id"]) + 1
        state["formats"][record["signatur"]["format"]] = int(record["signatur"]["nummer"]) + 1
        files = {
            record_path(record["id"]): render_photo_markdown(record),
            STATE_PATH: dump_state(state),
        }
        try:
            new_head = repository.commit_files(
                expected_head=head,
                files=files,
                message=f"Speichere {record['signatur']['anzeige']}",
            )
            return StoredRecord(data=record, body="", revision=new_head)
        except RepositoryConflictError as exc:
            last_conflict = exc
    raise RepositoryConflictError("Signaturvergabe konnte wegen paralleler Änderungen nicht abgeschlossen werden.") from last_conflict


def update_photo_record(repository: DataRepository, record_id: str, payload: dict[str, Any], user: User) -> StoredRecord:
    head = repository.get_branch_head()
    existing = read_photo_record(repository, record_id)
    if payload.get("base_revision") != existing.revision:
        raise RecordRevisionConflictError("Dieser Datensatz wurde inzwischen von einer anderen Person geändert. Bitte laden Sie die aktuelle Fassung neu.")
    if not can_edit_record(user, existing.data):
        raise RecordPermissionError("Keine Berechtigung zum Speichern dieses Datensatzes.")
    record = update_record(existing.data, payload, user)
    validate_canonical_record(record)
    try:
        new_head = repository.commit_files(
            expected_head=head,
            files={record_path(record_id): render_photo_markdown(record, existing.body)},
            message=f"Aktualisiere {record_id}",
        )
    except RepositoryConflictError as exc:
        raise RecordRevisionConflictError("Dieser Datensatz wurde inzwischen von einer anderen Person geändert. Bitte laden Sie die aktuelle Fassung neu.") from exc
    return StoredRecord(data=record, body=existing.body, revision=new_head)
