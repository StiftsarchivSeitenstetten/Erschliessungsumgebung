"""Shared semantic datatypes for archival module configurations.

The entries describe canonical data semantics, not a concrete form widget.
They are intentionally small in v1 and can be extended additively.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SemanticDatatype:
    key: str
    label: str
    description: str


CORE_DATATYPES: dict[str, SemanticDatatype] = {
    "agent": SemanticDatatype(
        key="agent",
        label="Akteur",
        description="Person, Körperschaft oder Familie mit optionaler Rolle oder Hinweis.",
    ),
    "place": SemanticDatatype(
        key="place",
        label="Ort",
        description="Geografischer Ort oder historischer Ortsbezug.",
    ),
    "date": SemanticDatatype(
        key="date",
        label="Datum",
        description="Einzelnes strukturiertes oder quellennahe beschriebenes Datum.",
    ),
    "date_range": SemanticDatatype(
        key="date_range",
        label="Datumsbereich",
        description="Zeitraum mit Beginn, optionalem Ende und optionalem Hinweis.",
    ),
    "term_ref": SemanticDatatype(
        key="term_ref",
        label="Vokabularreferenz",
        description="Stabile Referenz auf einen kontrollierten Vokabularwert.",
    ),
    "identifier": SemanticDatatype(
        key="identifier",
        label="Kennung",
        description="Fachliche oder technische Identifikationsnummer.",
    ),
    "record_ref": SemanticDatatype(
        key="record_ref",
        label="Datensatzreferenz",
        description="Stabile Referenz auf einen anderen Erschließungsdatensatz.",
    ),
    "digital_asset": SemanticDatatype(
        key="digital_asset",
        label="Digitalisat",
        description="Referenz auf eine digitale Repräsentation oder Datei.",
    ),
    "language": SemanticDatatype(
        key="language",
        label="Sprache",
        description="Sprachangabe, vorzugsweise mit stabilem Sprachcode.",
    ),
}


def list_datatypes() -> list[SemanticDatatype]:
    return [CORE_DATATYPES[key] for key in sorted(CORE_DATATYPES)]


def get_datatype(key: str) -> SemanticDatatype:
    return CORE_DATATYPES[key]
