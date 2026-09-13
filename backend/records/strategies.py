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
