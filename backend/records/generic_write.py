"""Module-defined record writes through the repository commit boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import yaml

from ..github.errors import RepositoryConflictError, RepositoryNotFoundError
from ..github.repository import DataRepository
from ..modules import ModuleDefinition, get_path_value, path_exists
from .generic_read import GenericStoredRecord, parse_record_file, record_path
from .identity import reservation_from_state, validate_operation_id
from .module_state import ModuleState
from .module_index import index_write_files
from .runtime import RecordRuntime, RecordValidationError
from .strategies import allocate_server_values


def render_record_content(record: dict[str, Any], previous_content: str | None = None) -> str:
    body = ""
    if previous_content and previous_content.startswith("---\n"):
        _, separator, previous_body = previous_content[4:].partition("\n---\n")
        if separator:
            body = previous_body
    frontmatter = yaml.safe_dump(record, allow_unicode=True, sort_keys=False)
    return f"---\n{frontmatter}---\n{body}"


def require_complete_update(module: ModuleDefinition, existing: dict[str, Any], payload: dict[str, Any], role: str) -> None:
    missing = [
        field.path
        for field in module.fields
        if field.can_edit(role) and path_exists(existing, field.path) and not path_exists(payload, field.path)
    ]
    if missing:
        raise RecordValidationError([f"Bearbeitbares Feld fehlt im PUT-Payload: {path}" for path in missing])


def create_generic_record(
    repository: DataRepository,
    module: ModuleDefinition,
    payload: dict[str, Any],
    user: Any,
    server_values: Mapping[str, Any] | None = None,
    operation_id: str | None = None,
    reserved_identity: Mapping[str, Any] | None = None,
) -> GenericStoredRecord:
    head = repository.get_branch_head()
    state = ModuleState(repository, module)
    values = dict(server_values or {})
    identity_assignment = module.create_strategy.get("identity_assignment", "on_create")
    if identity_assignment == "reserve_before_create":
        validate_operation_id(operation_id or "")
        reservation = reservation_from_state(state, module, operation_id or "", payload)
        if reservation is None:
            raise RecordValidationError(["Fuer diesen Create fehlt eine bestaetigte Identitaetsreservation."])
        if reserved_identity is None or dict(reserved_identity) != reservation.identity:
            raise RecordValidationError(["Reservierte Identitaet stimmt nicht mit dem Modul-State ueberein."])
        values.update(reservation.identity)
    elif identity_assignment == "on_create":
        if reserved_identity is not None:
            raise RecordValidationError(["Dieses Modul akzeptiert keine vorab reservierte Identitaet."])
        values.update(allocate_server_values(module, payload, state))
    else:
        raise RecordValidationError([f"Unbekannte Create-Strategie: {identity_assignment}"])
    if module.record_type:
        values["datensatz_typ"] = module.record_type
    record_id = values.get("id")
    if not isinstance(record_id, str) or not record_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in record_id):
        raise RecordValidationError(["Serverseitige technische ID fehlt oder ist ungueltig."])

    record = RecordRuntime(module).prepare_create(payload, user, server_values=values)
    path = record_path(module, record_id)
    try:
        repository.read_file(path)
    except RepositoryNotFoundError:
        pass
    else:
        raise RepositoryConflictError(f"Datensatz existiert bereits: {record_id}")

    content = render_record_content(record)
    files = {path: content, state.path: state.content()}
    files.update(index_write_files(repository, module, record, content, create=True))
    repository.commit_files(
        expected_head=head,
        files=files,
        message=f"Erzeuge {module.id} {record_id}",
    )
    return parse_record_file(repository.read_file(path))


def update_generic_record(
    repository: DataRepository,
    module: ModuleDefinition,
    record_id: str,
    payload: dict[str, Any],
    base_revision: str,
    user: Any,
) -> GenericStoredRecord:
    if not base_revision:
        raise RecordValidationError(["base_revision ist fuer PUT erforderlich."])
    head = repository.get_branch_head()
    path = record_path(module, record_id)
    previous_file = repository.read_file(path)
    previous = parse_record_file(previous_file)
    if previous.record_id != record_id:
        raise RecordValidationError(["Technische ID im gespeicherten Datensatz stimmt nicht mit dem Pfad ueberein."])
    if previous.revision != base_revision:
        raise RepositoryConflictError("Datensatz wurde zwischenzeitlich geaendert.")

    runtime = RecordRuntime(module)
    runtime.filter_for_edit(payload, user.role)
    require_complete_update(module, previous.data, payload, user.role)
    if module.signature_strategy.get("strategy") == "partitioned_sequence" and not module.signature_strategy.get("allow_update", False):
        partition_field = module.signature_strategy.get("partition_field", "signatur.format")
        proposed = get_path_value(payload, partition_field, get_path_value(previous.data, partition_field, None))
        if proposed != get_path_value(previous.data, partition_field, None):
            raise RecordValidationError(["Signaturpartition darf bei PUT nicht ohne explizite Modulfreigabe geaendert werden."])
    updated = runtime.prepare_update(previous.data, payload, user)
    content = render_record_content(updated, previous_file.content)
    files = {path: content}
    files.update(index_write_files(repository, module, updated, content, create=False))
    repository.commit_files(
        expected_head=head,
        files=files,
        message=f"Aktualisiere {module.id} {record_id}",
    )
    return parse_record_file(repository.read_file(path))
