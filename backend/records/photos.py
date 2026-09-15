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
from .photo_index import (
    INDEX_PATH,
    PhotoIndex,
    append_index_record,
    dump_photo_index,
    index_entry_changed,
    read_photo_index,
    record_path as indexed_record_path,
    update_index_record,
)


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


class ReservationConflictError(RuntimeError):
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
    return indexed_record_path(record_id)


def list_photo_index(repository: DataRepository) -> PhotoIndex:
    return read_photo_index(repository)


def list_photo_records(repository: DataRepository) -> list[dict[str, Any]]:
    return list_photo_index(repository).records


def read_photo_record(repository: DataRepository, record_id: str) -> StoredRecord:
    return parse_markdown_file(repository.read_file(record_path(record_id)))


def find_photo_by_signature(repository: DataRepository, signature: str) -> StoredRecord:
    entry = read_photo_index(repository).by_signature(signature)
    if entry is None:
        raise RepositoryNotFoundError(signature)
    return read_photo_record(repository, entry["id"])


def find_photo_signature_family(repository: DataRepository, base_signature: str) -> list[dict[str, Any]]:
    return read_photo_index(repository).signature_family(base_signature)


def bootstrap_state(repository: DataRepository) -> dict[str, Any]:
    config = load_config()
    formats = {format_code: 1 for format_code in config["signature"]["formats"]}
    max_id = 0
    try:
        index = read_photo_index(repository)
        records = [read_photo_record(repository, entry["id"]) for entry in index.records]
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
    return {"next_id": max_id + 1, "formats": formats, "reservations": {}}


def normalize_state(raw_state: dict[str, Any]) -> dict[str, Any]:
    if "next_id" in raw_state and "formats" in raw_state:
        return {
            **raw_state,
            "reservations": dict(raw_state.get("reservations") or {}),
        }
    if "next_record_id" in raw_state and "next_signature_number" in raw_state:
        return {
            "next_id": int(raw_state["next_record_id"]),
            "formats": {key: int(value) for key, value in raw_state["next_signature_number"].items()},
            "reservations": dict(raw_state.get("reservations") or {}),
        }
    return raw_state


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_state(state)
    return {
        "next_record_id": int(normalized["next_id"]),
        "next_signature_number": {
            key: int(value)
            for key, value in sorted(normalized["formats"].items())
        },
        "reservations": normalized.get("reservations") or {},
    }


def read_state(repository: DataRepository) -> dict[str, Any]:
    try:
        return normalize_state(json.loads(repository.read_file(STATE_PATH).content))
    except RepositoryNotFoundError:
        return bootstrap_state(repository)


def dump_state(state: dict[str, Any]) -> str:
    return json.dumps(public_state(state), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


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


def allocate_photo_identity(state: dict[str, Any], partition: str) -> tuple[str, dict[str, Any]]:
    config = load_config()
    partition = str(partition).upper()
    if partition not in config["signature"]["formats"]:
        raise RecordValidationError(["format ist unzulaessig."])
    record_id = f"foto-{int(state['next_id']):06d}"
    number = int(state["formats"][partition])
    return record_id, build_signature(partition, number, config, status="vergeben")


def build_new_record(
    payload: dict[str, Any],
    user: User,
    record_id: str,
    signature: dict[str, Any],
) -> dict[str, Any]:
    config = load_config()
    now = utc_iso()
    return {
        "schema_version": 1,
        "id": record_id,
        "datensatz_typ": config["datensatz_typ"],
        "modul": config["module_id"],
        "signatur": signature,
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
            "geaendert_am": now,
            "geaendert_von": user.username,
        },
    }


def reservation_response(reservation: dict[str, Any]) -> dict[str, Any]:
    return {
        "operation_id": reservation["operation_id"],
        "record_id": reservation["record_id"],
        "signature": reservation["signature"],
        "partition": reservation["partition"],
        "reserved_at": reservation["reserved_at"],
    }


def reserve_photo_identity(repository: DataRepository, operation_id: str, partition: str) -> dict[str, Any]:
    operation_id = str(operation_id)
    partition = str(partition).upper()
    last_conflict: RepositoryConflictError | None = None
    for _ in range(MAX_RETRIES):
        head = repository.get_branch_head()
        state = read_state(repository)
        existing = state["reservations"].get(operation_id)
        if existing is not None:
            if existing["partition"] != partition:
                raise ReservationConflictError("Diese operation_id ist bereits für eine andere Partition reserviert.")
            return reservation_response(existing)

        record_id, signature = allocate_photo_identity(state, partition)
        reservation = {
            "operation_id": operation_id,
            "record_id": record_id,
            "signature": signature["anzeige"],
            "partition": partition,
            "reserved_at": utc_iso(),
            "signature_data": signature,
        }
        state["next_id"] = int(state["next_id"]) + 1
        state["formats"][partition] = int(state["formats"][partition]) + 1
        state["reservations"][operation_id] = reservation
        try:
            repository.commit_files(
                expected_head=head,
                files={STATE_PATH: dump_state(state)},
                message=f"Reserviere {signature['anzeige']} für {operation_id}",
            )
            return reservation_response(reservation)
        except RepositoryConflictError as exc:
            last_conflict = exc
    raise RepositoryConflictError("Foto-ID und Signatur konnten nicht reserviert werden.") from last_conflict


def reserved_identity(state: dict[str, Any], payload: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    raw_operation_id = payload.get("operation_id")
    if raw_operation_id is None:
        if payload.get("record_id") is not None or payload.get("signature") is not None:
            raise ReservationConflictError("Reservierte Record-ID und Signatur benötigen eine operation_id.")
        return None
    operation_id = str(raw_operation_id)
    reservation = state["reservations"].get(operation_id)
    if reservation is None:
        raise ReservationConflictError("Für diese operation_id liegt keine Reservierung vor.")
    if payload.get("record_id") != reservation["record_id"]:
        raise ReservationConflictError("record_id stimmt nicht mit der Reservierung überein.")
    if payload.get("signature") != reservation["signature"]:
        raise ReservationConflictError("Signatur stimmt nicht mit der Reservierung überein.")
    if str(payload.get("format", "")).upper() != reservation["partition"]:
        raise ReservationConflictError("Partition stimmt nicht mit der Reservierung überein.")
    return reservation["record_id"], dict(reservation["signature_data"])


def update_record(existing: dict[str, Any], payload: dict[str, Any], user: User) -> dict[str, Any]:
    updated = dict(existing)
    updated["erschliessung"] = canonical_erschliessung(payload.get("erschliessung") or existing.get("erschliessung", {}))
    updated["korrespondenzstueck"] = bool(payload.get("korrespondenzstueck", existing.get("korrespondenzstueck", False)))
    updated["datierung"] = payload.get("datierung") or existing.get("datierung") or {"jahr": None, "monat": None, "tag": None}
    technik = dict(existing.get("technik") or {})
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
        index = read_photo_index(repository)
        identity = reserved_identity(state, payload)
        if identity is None:
            record_id, signature = allocate_photo_identity(state, payload.get("format", ""))
            state["next_id"] = int(state["next_id"]) + 1
            state["formats"][signature["format"]] = int(state["formats"][signature["format"]]) + 1
        else:
            record_id, signature = identity
            try:
                return read_photo_record(repository, record_id)
            except RepositoryNotFoundError:
                pass
        record = build_new_record(payload, user, record_id, signature)
        validate_canonical_record(record)
        files = {
            record_path(record["id"]): render_photo_markdown(record),
            INDEX_PATH: dump_photo_index(append_index_record(index, record)),
        }
        if identity is None:
            files[STATE_PATH] = dump_state(state)
        try:
            repository.commit_files(
                expected_head=head,
                files=files,
                message=f"Speichere {record['signatur']['anzeige']}",
            )
            return read_photo_record(repository, record["id"])
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
    files = {record_path(record_id): render_photo_markdown(record, existing.body)}
    if index_entry_changed(existing.data, record):
        files[INDEX_PATH] = dump_photo_index(update_index_record(read_photo_index(repository), record))
    try:
        repository.commit_files(
            expected_head=head,
            files=files,
            message=f"Aktualisiere {record_id}",
        )
    except RepositoryConflictError as exc:
        raise RecordRevisionConflictError("Dieser Datensatz wurde inzwischen von einer anderen Person geändert. Bitte laden Sie die aktuelle Fassung neu.") from exc
    return read_photo_record(repository, record_id)
