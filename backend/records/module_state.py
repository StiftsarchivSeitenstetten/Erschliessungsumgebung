"""Repository-backed counters shared by configured allocation strategies."""

from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from ..github.errors import RepositoryNotFoundError
from ..github.repository import DataRepository
from ..modules import ModuleDefinition
from .runtime import RecordValidationError


class ModuleState:
    def __init__(self, repository: DataRepository, module: ModuleDefinition):
        config = module.storage.get("state") or {}
        self.path = config.get("path")
        if not isinstance(self.path, str) or not self.path:
            raise RecordValidationError(["Modul-State-Pfad ist nicht konfiguriert."])
        try:
            source = repository.read_file(self.path).content
        except RepositoryNotFoundError as exc:
            raise RecordValidationError([f"Modul-State fehlt: {self.path}"]) from exc
        try:
            data = json.loads(source)
        except (ValueError, TypeError) as exc:
            raise RecordValidationError(["Modul-State ist kein gueltiges JSON."]) from exc
        if not isinstance(data, dict):
            raise RecordValidationError(["Modul-State muss ein Objekt sein."])
        self.data: dict[str, Any] = deepcopy(data)

    def next_number(self, key: str, partition: str | None = None) -> int:
        counters = self.data.get(key)
        if partition is not None:
            if not isinstance(counters, dict):
                raise RecordValidationError([f"Modul-State-Zaehler fehlt: {key}"])
            value = counters.get(partition)
        else:
            value = counters
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise RecordValidationError([f"Modul-State-Zaehler fehlt oder ist ungueltig: {key}/{partition or ''}"])
        if partition is None:
            self.data[key] = value + 1
        else:
            counters[partition] = value + 1
        return value

    def content(self) -> str:
        return json.dumps(self.data, ensure_ascii=False, indent=2) + "\n"

    def reservation(self, operation_id: str) -> dict[str, Any] | None:
        reservations = self.data.get("identity_reservations") or {}
        if not isinstance(reservations, dict):
            raise RecordValidationError(["Identitaetsreservationen im Modul-State sind ungueltig."])
        reservation = reservations.get(operation_id)
        if reservation is None:
            return None
        if not isinstance(reservation, dict):
            raise RecordValidationError(["Identitaetsreservation im Modul-State ist ungueltig."])
        return deepcopy(reservation)

    def set_reservation(self, operation_id: str, reservation: dict[str, Any]) -> None:
        reservations = self.data.setdefault("identity_reservations", {})
        if not isinstance(reservations, dict):
            raise RecordValidationError(["Identitaetsreservationen im Modul-State sind ungueltig."])
        reservations[operation_id] = deepcopy(reservation)

    def create_operation(self, operation_id: str) -> dict[str, Any] | None:
        operations = self.data.get("create_operations") or {}
        if not isinstance(operations, dict):
            raise RecordValidationError(["Create-Operationen im Modul-State sind ungueltig."])
        operation = operations.get(operation_id)
        if operation is None:
            return None
        if not isinstance(operation, dict):
            raise RecordValidationError(["Create-Operation im Modul-State ist ungueltig."])
        return deepcopy(operation)

    def set_create_operation(self, operation_id: str, operation: dict[str, Any]) -> None:
        operations = self.data.setdefault("create_operations", {})
        if not isinstance(operations, dict):
            raise RecordValidationError(["Create-Operationen im Modul-State sind ungueltig."])
        operations[operation_id] = deepcopy(operation)
