"""Conservative, row-independent write policy for repeaters without row IDs."""

from dataclasses import dataclass, field as dataclass_field
from typing import Any


class UnsafeRepeaterError(ValueError):
    pass


@dataclass
class RepeaterPlan:
    constants: dict[str, Any] = dataclass_field(default_factory=dict)
    children: dict[str, "RepeaterPlan"] = dataclass_field(default_factory=dict)
    properties: dict[str, Any] = dataclass_field(default_factory=dict)
    mixed: bool = False


def repeater_plan(field, schema, role, resolve, prefix=None):
    """Prove every non-editable row value required and constant, or fail closed."""
    prefix = prefix or field.path
    schema = resolve(schema)
    plan = RepeaterPlan()
    # Without restricted descendants the entire row (including structured,
    # non-rendered values) is writable and travels in the replacement payload.
    if not field.has_protected_items(role):
        return plan
    if not isinstance(schema, dict) or not isinstance(schema.get("items"), dict):
        raise UnsafeRepeaterError(f"{prefix}: Zeilenschema ist nicht eindeutig auswertbar.")
    item = resolve(schema["items"])
    declared = {child.path: child for child in field.item_fields}
    structures = [schema]

    def fail(path, reason):
        raise UnsafeRepeaterError(f"{prefix}[].{path}: {reason}")

    def walk(node, path="", required=True):
        node = resolve(node)
        if not isinstance(node, dict):
            fail(path, "Zeilenstruktur ist nicht eindeutig auswertbar.")
        child = declared.get(path)
        if child is not None and child.can_edit(role):
            if child.widget == "repeater":
                nested = repeater_plan(child, node, role, resolve, f"{prefix}[].{path}")
                plan.children[path] = nested
                plan.mixed |= nested.mixed
            return
        if path and (child is not None or not any(p.startswith(path + ".") for p in declared)):
            if child is not None and child.item_fields:
                fail(path, "Vollständig geschützte strukturierte Gruppen werden ohne Zeilenidentität nicht unterstützt.")
            if not required or "const" not in node:
                fail(path, "Geschütztes oder nicht deklariertes Zeilenfeld benötigt ein erforderliches Schema-const; ein Default genügt nicht.")
            if any(key in node for key in ("allOf", "anyOf", "oneOf", "if", "then", "else", "$ref")):
                fail(path, "Geschützte Konstante ist nicht eindeutig auswertbar.")
            plan.constants[path] = node["const"]
            plan.mixed = True
            return
        structures.append(node)
        if node.get("type") != "object" or not isinstance(node.get("properties"), dict):
            fail(path, "Repeater benötigt eindeutig deklarierte Objektfelder.")
        for key, value in node["properties"].items():
            walk(value, f"{path}.{key}" if path else key, required and key in node.get("required", []))

    walk(item)
    for path in declared:
        node = item
        for part in path.split("."):
            node = resolve(node).get("properties", {}).get(part, {})
        if not node:
            fail(path, "Formularfeld fehlt im kanonischen Zeilenschema.")
    if plan.mixed:
        for node in structures:
            if any(key in node for key in ("allOf", "anyOf", "oneOf", "if", "then", "else", "patternProperties", "dependentSchemas", "unevaluatedProperties", "$ref")):
                fail("<Struktur>", "Gemischte Zeilenstruktur ist nicht eindeutig auswertbar.")
            if node is not schema and node.get("additionalProperties") is not False:
                fail("<Struktur>", "Gemischte Zeilen benötigen additionalProperties: false.")
    plan.properties = item
    return plan
