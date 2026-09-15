"""Module-independent allocation strategies; state persistence is handled elsewhere."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..modules import ModuleDefinition, get_path_value
from .module_state import ModuleState
from .runtime import RecordValidationError


def prefixed_sequence(config: dict[str, Any], payload: dict[str, Any], state: ModuleState) -> dict[str, Any]:
    number = state.next_number("next_record_id")
    return {"id": f"{config['prefix']}{number:0{config['width']}d}"}


def partitioned_sequence(config: dict[str, Any], payload: dict[str, Any], state: ModuleState) -> dict[str, Any]:
    partitions = config["partitions"]
    partition_field = config.get("partition_field", "signatur.format")
    partition = get_path_value(payload, partition_field, None)
    if partition is None and len(partitions) == 1:
        partition = partitions[0]
    if partition not in partitions:
        raise RecordValidationError([f"Ungueltige Signaturpartition: {partition!r}"])
    number = state.next_number("next_signature_number", partition)
    context = {
        "partition": partition,
        "number": number,
        "format": partition,
        "nummer": number,
        **{key: value for key, value in config.items() if isinstance(value, (str, int))},
    }
    try:
        display = config["pattern"].format_map(context)
    except (KeyError, ValueError) as exc:
        raise RecordValidationError(["Signaturmuster kann nicht aufgeloest werden."]) from exc
    root = config.get("output_path", "signatur")
    values = {
        f"{root}.format": partition,
        f"{root}.nummer": number,
        f"{root}.anzeige": display,
    }
    for key in ("bestand", "objektgruppe"):
        if key in config:
            values[f"{root}.{key}"] = config[key]
    if "vergeben" in config.get("status_values", []):
        values[f"{root}.status"] = "vergeben"
    return values


ID_STRATEGIES: dict[str, Callable[[dict[str, Any], dict[str, Any], ModuleState], dict[str, Any]]] = {
    "prefixed_sequence": prefixed_sequence,
}
SIGNATURE_STRATEGIES: dict[str, Callable[[dict[str, Any], dict[str, Any], ModuleState], dict[str, Any]]] = {
    "partitioned_sequence": partitioned_sequence,
}


def allocate_server_values(module: ModuleDefinition, payload: dict[str, Any], state: ModuleState) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for config, registry in ((module.id_strategy, ID_STRATEGIES), (module.signature_strategy, SIGNATURE_STRATEGIES)):
        if not config:
            continue
        strategy = registry.get(config.get("strategy"))
        if strategy is None:
            raise RecordValidationError([f"Unbekannte Vergabestrategie: {config.get('strategy')}"])
        values.update(strategy(config, payload, state))
    return values


def suggest_server_values(module: ModuleDefinition, payload: dict[str, Any], state: ModuleState) -> dict[str, Any]:
    """Preview the next configured identity without persisting or reserving it."""
    return allocate_server_values(module, payload, state)


def identity_request(module: ModuleDefinition, payload: dict[str, Any]) -> dict[str, Any]:
    request: dict[str, Any] = {}
    if module.id_strategy:
        request["id"] = {"strategy": module.id_strategy.get("strategy"), "inputs": {}}
    if module.signature_strategy:
        config = module.signature_strategy
        inputs: dict[str, Any] = {}
        if config.get("strategy") == "partitioned_sequence":
            path = config.get("partition_field", "signatur.format")
            partition = get_path_value(payload, path, None)
            if partition is None and len(config.get("partitions") or ()) == 1:
                partition = config["partitions"][0]
            inputs[path] = partition
        request["signature"] = {"strategy": config.get("strategy"), "inputs": inputs}
    return request
