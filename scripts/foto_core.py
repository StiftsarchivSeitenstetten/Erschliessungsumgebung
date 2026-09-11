"""Core logic for the 9.4.2 paper print photo pilot.

The module intentionally has no third-party dependencies so it can run in
GitHub Actions and on plain local Python installations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
import re
from typing import Any


VALID_FORMATS = ("A", "B", "C", "D", "E", "F")
VALID_REDAKTIONSSTUFEN = ("ehrenamtlich", "redaktionell")
VALID_BEARBEITUNGSSTATUS = ("in_bearbeitung", "pruefen", "abgeschlossen")
VALID_PUBLIKATIONSSTATUS = ("intern", "oeffentlich")
MODULE_ID = "papierabzuege_9_4_2"
BESTAND = "9.4"
OBJEKTGRUPPE = "2"


@dataclass(frozen=True)
class MarkdownRecord:
    path: Path
    data: dict[str, Any]
    body: str


def build_signature(format_code: str, number: int) -> dict[str, Any]:
    format_code = format_code.upper()
    if format_code not in VALID_FORMATS:
        raise ValueError(f"Ungueltiges Format: {format_code}")
    if not isinstance(number, int) or number < 1:
        raise ValueError("Nummer muss eine positive Ganzzahl sein")
    return {
        "bestand": BESTAND,
        "objektgruppe": OBJEKTGRUPPE,
        "format": format_code,
        "nummer": number,
        "anzeige": f"{BESTAND}.{OBJEKTGRUPPE}.{format_code}.{number}",
        "status": "vergeben",
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


def next_number(records: list[dict[str, Any]], format_code: str) -> int:
    format_code = format_code.upper()
    if format_code not in VALID_FORMATS:
        raise ValueError(f"Ungueltiges Format: {format_code}")
    numbers = [
        record.get("signatur", {}).get("nummer")
        for record in records
        if record.get("signatur", {}).get("format") == format_code
    ]
    numbers = [number for number in numbers if isinstance(number, int)]
    return max(numbers, default=0) + 1


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
    return MarkdownRecord(path=path, data=parse_simple_yaml(yaml_text), body=body)


def load_records(data_dir: Path) -> list[MarkdownRecord]:
    return [load_markdown_record(path) for path in sorted(data_dir.glob("foto-*.md"))]


def parse_simple_yaml(text: str) -> Any:
    lines = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        lines.append((indent, raw.strip()))
    value, index = _parse_block(lines, 0, 0)
    if index != len(lines):
        raise ValueError(f"YAML konnte ab Zeile {index + 1} nicht gelesen werden")
    return value


def _parse_block(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    current_indent, stripped = lines[index]
    if current_indent < indent:
        return {}, index
    if stripped.startswith("- "):
        return _parse_list(lines, index, current_indent)
    return _parse_dict(lines, index, current_indent)


def _parse_list(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[list[Any], int]:
    result = []
    while index < len(lines):
        current_indent, stripped = lines[index]
        if current_indent != indent or not stripped.startswith("- "):
            break
        item = stripped[2:].strip()
        index += 1
        if not item:
            nested, index = _parse_block(lines, index, indent + 2)
            result.append(nested)
            continue
        if _looks_like_key_value(item):
            key, raw_value = item.split(":", 1)
            entry: dict[str, Any] = {key.strip(): _parse_scalar(raw_value.strip())}
            if index < len(lines) and lines[index][0] > indent:
                nested, index = _parse_block(lines, index, indent + 2)
                if isinstance(nested, dict):
                    entry.update(nested)
            result.append(entry)
        else:
            result.append(_parse_scalar(item))
    return result, index


def _parse_dict(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines):
        current_indent, stripped = lines[index]
        if current_indent != indent or stripped.startswith("- "):
            break
        if ":" not in stripped:
            raise ValueError(f"Ungueltige YAML-Zeile: {stripped}")
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        index += 1
        if raw_value == "":
            nested, index = _parse_block(lines, index, indent + 2)
            result[key] = nested
        else:
            result[key] = _parse_scalar(raw_value)
    return result, index


def _looks_like_key_value(value: str) -> bool:
    return bool(re.match(r"^[A-Za-z0-9_]+:", value))


def _parse_scalar(value: str) -> Any:
    if value == "[]":
        return []
    if value == "{}":
        return {}
    if value in ("null", "~"):
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    if re.match(r"^-?[0-9]+$", value):
        return int(value)
    return value


def validate_record(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    _require(record, "id", errors)
    _require(record, "signatur", errors)
    _require(record, "erschliessung", errors)
    _require(record, "datierung", errors)
    _require(record, "redaktion", errors)
    _require(record, "bearbeitung", errors)
    _require(record, "publikation", errors)

    record_id = record.get("id")
    if record_id and not re.match(r"^foto-[0-9]{6}$", str(record_id)):
        errors.append("id muss dem Muster foto-000001 entsprechen")

    if record.get("modul") != MODULE_ID:
        errors.append(f"modul muss {MODULE_ID} sein")

    errors.extend(validate_signature(record.get("signatur", {})))
    errors.extend(validate_datierung(record.get("datierung", {})))

    redaktion = record.get("redaktion", {})
    if redaktion.get("stufe") not in VALID_REDAKTIONSSTUFEN:
        errors.append("redaktion.stufe ist unzulaessig")

    bearbeitung = record.get("bearbeitung", {})
    if bearbeitung.get("status") not in VALID_BEARBEITUNGSSTATUS:
        errors.append("bearbeitung.status ist unzulaessig")

    publikation = record.get("publikation", {})
    if publikation.get("status") not in VALID_PUBLIKATIONSSTATUS:
        errors.append("publikation.status ist unzulaessig")

    erschliessung = record.get("erschliessung", {})
    for list_field in ("dargestellte_personen", "orte", "schlagworte", "altsignaturen"):
        if not isinstance(erschliessung.get(list_field), list):
            errors.append(f"erschliessung.{list_field} muss eine Liste sein")

    return errors


def validate_signature(signatur: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if signatur.get("bestand") != BESTAND:
        errors.append("signatur.bestand muss 9.4 sein")
    if signatur.get("objektgruppe") != OBJEKTGRUPPE:
        errors.append("signatur.objektgruppe muss 2 sein")
    format_code = signatur.get("format")
    if format_code not in VALID_FORMATS:
        errors.append("signatur.format muss A-F sein")
    number = signatur.get("nummer")
    if not isinstance(number, int) or number < 1:
        errors.append("signatur.nummer muss eine positive Ganzzahl sein")
    if format_code in VALID_FORMATS and isinstance(number, int):
        expected = f"{BESTAND}.{OBJEKTGRUPPE}.{format_code}.{number}"
        if signatur.get("anzeige") != expected:
            errors.append("signatur.anzeige entspricht nicht den Einzelkomponenten")
    if signatur.get("status") not in ("vorgeschlagen", "vergeben"):
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
    errors: list[str] = []
    seen_ids: dict[str, Path] = {}
    seen_signatures: dict[str, Path] = {}
    for markdown_record in records:
        prefix = str(markdown_record.path)
        for error in validate_record(markdown_record.data):
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


def _require(record: dict[str, Any], key: str, errors: list[str]) -> None:
    if key not in record:
        errors.append(f"{key} fehlt")
