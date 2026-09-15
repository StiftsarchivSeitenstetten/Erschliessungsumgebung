"""Idempotent module-configured identity reservation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from ..github.repository import DataRepository
from ..modules import ModuleDefinition
from .module_state import ModuleState
from .runtime import RecordValidationError
from .strategies import allocate_server_values, identity_request


@dataclass(frozen=True)
class ReservedIdentity:
    operation_id: str
    record_id: str
    identity: dict[str, Any]


def require_reservation_strategy(module: ModuleDefinition) -> None:
    if module.create_strategy.get("identity_assignment") != "reserve_before_create":
        raise RecordValidationError(["Dieses Modul verwendet keine Identitaetsreservation."])


def validate_operation_id(operation_id: str) -> None:
    if not isinstance(operation_id, str) or not operation_id.strip() or len(operation_id) > 200:
        raise RecordValidationError(["operation_id fehlt oder ist ungueltig."])


def reservation_from_state(
    state: ModuleState,
    module: ModuleDefinition,
    operation_id: str,
    payload: dict[str, Any],
) -> ReservedIdentity | None:
    stored = state.reservation(operation_id)
    if stored is None:
        return None
    if stored.get("request") != identity_request(module, payload):
        raise RecordValidationError(["operation_id wurde bereits mit anderen Identitaetseingaben verwendet."])
    identity = stored.get("identity")
    if not isinstance(identity, dict) or not isinstance(identity.get("id"), str):
        raise RecordValidationError(["Gespeicherte Identitaetsreservation ist ungueltig."])
    return ReservedIdentity(operation_id=operation_id, record_id=identity["id"], identity=deepcopy(identity))


def reserve_generic_identity(
    repository: DataRepository,
    module: ModuleDefinition,
    operation_id: str,
    payload: dict[str, Any],
) -> ReservedIdentity:
    require_reservation_strategy(module)
    validate_operation_id(operation_id)
    head = repository.get_branch_head()
    state = ModuleState(repository, module)
    existing = reservation_from_state(state, module, operation_id, payload)
    if existing is not None:
        return existing
    identity = allocate_server_values(module, payload, state)
    record_id = identity.get("id")
    if not isinstance(record_id, str) or not record_id:
        raise RecordValidationError(["Reservationsstrategie hat keine Record-ID erzeugt."])
    state.set_reservation(operation_id, {
        "request": identity_request(module, payload),
        "identity": identity,
    })
    repository.commit_files(
        expected_head=head,
        files={state.path: state.content()},
        message=f"Reserviere Identitaet fuer {module.id}",
    )
    return ReservedIdentity(operation_id=operation_id, record_id=record_id, identity=deepcopy(identity))
