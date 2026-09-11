"""Core logic for the 9.4.2 paper print photo pilot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import re
from typing import Any

import jsonschema
import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "foto-papierabzuege.json"
SCHEMA_PATH = ROOT / "schemas" / "foto.schema.json"


@dataclass(frozen=True)
class MarkdownRecord:
    path: Path
    data: dict[str, Any]
    body: str


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_schema(path: Path = SCHEMA_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def signature_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    return (config or load_config())["signature"]


def valid_formats(config: dict[str, Any] | None = None) -> tuple[str, ...]:
    return tuple(signature_config(config)["formats"])


def build_signature(
    format_code: str,
    number: int,
    config: dict[str, Any] | None = None,
    status: str = "vergeben",
) -> dict[str, Any]:
    config = config or load_config()
    signature = signature_config(config)
    format_code = format_code.upper()
    if format_code not in signature["formats"]:
        raise ValueError(f"Ungueltiges Format: {format_code}")
    if not isinstance(number, int) or number < 1:
        raise ValueError("Nummer muss eine positive Ganzzahl sein")
    if status not in signature["status_values"]:
        raise ValueError(f"Ungueltiger Signaturstatus: {status}")
    anzeige = signature["pattern"].format(
        bestand=signature["bestand"],
        objektgruppe=signature["objektgruppe"],
        format=format_code,
        nummer=number,
    )
    return {
        "bestand": signature["bestand"],
        "objektgruppe": signature["objektgruppe"],
        "format": format_code,
        "nummer": number,
        "anzeige": anzeige,
        "status": status,
    }


def archivis_date_value(datierung: dict[str, Any]) -> str:
    year = datierung.get("jahr")
    month = datierung.get("monat")
    day = datierung.get("tag")
    if year in (None, ""):
        return ""
    if month in (None, ""):
        return f"{int(year):04d}9999"
    if day in (None, ""):
        return f"{int(year):04d}{int(month):02d}99"
    return f"{int(year):04d}{int(month):02d}{int(day):02d}"


def next_number(records: list[dict[str, Any]], format_code: str, config: dict[str, Any] | None = None) -> int:
    formats = valid_formats(config)
    format_code = format_code.upper()
    if format_code not in formats:
        raise ValueError(f"Ungueltiges Format: {format_code}")
    numbers = [
        record.get("signatur", {}).get("nummer")
        for record in records
        if record.get("signatur", {}).get("format") == format_code
    ]
    numbers = [number for number in numbers if isinstance(number, int)]
    return max(numbers, default=0) + 1


def next_id(records: list[dict[str, Any]]) -> str:
    numbers = []
    for record in records:
        record_id = str(record.get("id", ""))
        match = re.match(r"^foto-([0-9]{6})$", record_id)
        if match:
            numbers.append(int(match.group(1)))
    return f"foto-{max(numbers, default=0) + 1:06d}"


def append_local_record(records: list[dict[str, Any]], format_code: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a minimal local draft and add it to the in-session inventory.

    This mirrors the browser behavior: local drafts advance IDs and format
    numbers, but they are not a multi-user-safe reservation.
    """

    config = config or load_config()
    record = {
        "id": next_id(records),
        "signatur": build_signature(
            format_code,
            next_number(records, format_code, config),
            config,
            status="vorgeschlagen",
        ),
    }
    records.append(record)
    return record


def extract_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        raise ValueError("Markdown-Datei beginnt nicht mit YAML-Frontmatter")
    end = text.find("\n---", 4)
    if end == -1:
        raise ValueError("YAML-Frontmatter ist nicht geschlossen")
    yaml_text = text[4:end].strip("\n")
    body = text[end + 4 :].lstrip("\n")
    return yaml_text, body


def load_markdown_record(path: Path) -> MarkdownRecord:
    yaml_text, body = extract_frontmatter(path.read_text(encoding="utf-8"))
    parsed = yaml.safe_load(yaml_text)
    if not isinstance(parsed, dict):
        raise ValueError(f"{path}: YAML-Frontmatter ist kein Mapping")
    return MarkdownRecord(path=path, data=parsed, body=body)


def load_records(data_dir: Path) -> list[MarkdownRecord]:
    return [load_markdown_record(path) for path in sorted(data_dir.glob("foto-*.md"))]


def validate_record_schema(record: dict[str, Any], schema: dict[str, Any] | None = None) -> list[str]:
    schema = schema or load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    errors = []
    for error in sorted(validator.iter_errors(record), key=lambda item: list(item.path)):
        location = ".".join(str(part) for part in error.path) or "<root>"
        errors.append(f"Schemafehler {location}: {error.message}")
    return errors


def validate_record(record: dict[str, Any], config: dict[str, Any] | None = None) -> list[str]:
    config = config or load_config()
    errors: list[str] = []

    if record.get("modul") != config["module_id"]:
        errors.append(f"modul muss {config['module_id']} sein")

    errors.extend(validate_signature(record.get("signatur", {}), config))
    errors.extend(validate_datierung(record.get("datierung", {})))

    vocabularies = config["vocabularies"]
    redaktion = record.get("redaktion", {})
    if redaktion.get("stufe") not in vocabularies["redaktionsstufen"]:
        errors.append("redaktion.stufe ist unzulaessig")

    bearbeitung = record.get("bearbeitung", {})
    if bearbeitung.get("status") not in vocabularies["bearbeitungsstatus"]:
        errors.append("bearbeitung.status ist unzulaessig")

    publikation = record.get("publikation", {})
    if publikation.get("status") not in vocabularies["publikationsstatus"]:
        errors.append("publikation.status ist unzulaessig")

    erschliessung = record.get("erschliessung", {})
    for list_field in ("dargestellte_personen", "orte", "schlagworte", "altsignaturen"):
        if not isinstance(erschliessung.get(list_field), list):
            errors.append(f"erschliessung.{list_field} muss eine Liste sein")

    return errors


def validate_signature(signatur: dict[str, Any], config: dict[str, Any] | None = None) -> list[str]:
    config = config or load_config()
    signature = signature_config(config)
    errors: list[str] = []
    if signatur.get("bestand") != signature["bestand"]:
        errors.append(f"signatur.bestand muss {signature['bestand']} sein")
    if signatur.get("objektgruppe") != signature["objektgruppe"]:
        errors.append(f"signatur.objektgruppe muss {signature['objektgruppe']} sein")
    format_code = signatur.get("format")
    if format_code not in signature["formats"]:
        errors.append("signatur.format ist unzulaessig")
    number = signatur.get("nummer")
    if not isinstance(number, int) or number < 1:
        errors.append("signatur.nummer muss eine positive Ganzzahl sein")
    if format_code in signature["formats"] and isinstance(number, int):
        status = signatur.get("status", "vergeben")
        expected = build_signature(format_code, number, config, status)["anzeige"]
        if signatur.get("anzeige") != expected:
            errors.append("signatur.anzeige entspricht nicht den Einzelkomponenten")
    if signatur.get("status") not in signature["status_values"]:
        errors.append("signatur.status ist unzulaessig")
    return errors


def validate_datierung(datierung: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    year = datierung.get("jahr")
    month = datierung.get("monat")
    day = datierung.get("tag")
    if year is not None and (not isinstance(year, int) or not 1 <= year <= 9999):
        errors.append("datierung.jahr muss 1-9999 oder leer sein")
    if month is not None and (not isinstance(month, int) or not 1 <= month <= 12):
        errors.append("datierung.monat muss 1-12 oder leer sein")
    if day is not None:
        if not isinstance(day, int) or day < 1:
            errors.append("datierung.tag muss eine positive Zahl oder leer sein")
        elif year is not None and month is not None:
            try:
                date(year, month, day)
            except ValueError:
                errors.append("datierung.tag ist fuer Jahr/Monat nicht plausibel")
        elif month is None:
            errors.append("datierung.tag darf nicht ohne Monat gesetzt sein")
    if month is not None and year is None:
        errors.append("datierung.monat darf nicht ohne Jahr gesetzt sein")
    return errors


def validate_collection(records: list[MarkdownRecord]) -> list[str]:
    config = load_config()
    schema = load_schema()
    errors: list[str] = []
    seen_ids: dict[str, Path] = {}
    seen_signatures: dict[str, Path] = {}
    for markdown_record in records:
        prefix = str(markdown_record.path)
        for error in validate_record_schema(markdown_record.data, schema):
            errors.append(f"{prefix}: {error}")
        for error in validate_record(markdown_record.data, config):
            errors.append(f"{prefix}: {error}")
        record_id = markdown_record.data.get("id")
        if record_id in seen_ids:
            errors.append(f"{prefix}: id ist nicht eindeutig: {record_id}")
        elif record_id:
            seen_ids[record_id] = markdown_record.path
        signature = markdown_record.data.get("signatur", {}).get("anzeige")
        if signature in seen_signatures:
            errors.append(f"{prefix}: Signatur ist nicht eindeutig: {signature}")
        elif signature:
            seen_signatures[signature] = markdown_record.path
    return errors
