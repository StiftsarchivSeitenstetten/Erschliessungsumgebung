#!/usr/bin/env python3
"""Export selected photo fields as Archivis/Excel-compatible CSV."""

from __future__ import annotations

import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from foto_core import archivis_date_value, load_records  # noqa: E402


def yes_no_empty(value: object) -> str:
    if value is True:
        return "Ja"
    if value is False:
        return "Nein"
    return ""


FIELDS = [
    "id",
    "Signatur",
    "Format",
    "Nummer",
    "Titel",
    "Beschriftung",
    "Beschreibung",
    "DatierungArchivis",
    "Korrespondenzstueck",
    "Herkunft",
    "Sammler",
    "Fotograf",
    "Rechteinhaber",
    "Orte",
    "Schlagworte",
    "Altsignatur",
    "InterneBemerkung",
]


def main() -> int:
    records = load_records(ROOT / "data" / "fotos")
    writer = csv.DictWriter(sys.stdout, fieldnames=FIELDS)
    writer.writeheader()
    for markdown_record in records:
        data = markdown_record.data
        erschliessung = data["erschliessung"]
        signatur = data["signatur"]
        writer.writerow(
            {
                "id": data["id"],
                "Signatur": signatur["anzeige"],
                "Format": signatur["format"],
                "Nummer": signatur["nummer"],
                "Titel": erschliessung.get("titel") or "",
                "Beschriftung": erschliessung.get("beschriftung") or "",
                "Beschreibung": erschliessung.get("beschreibung") or "",
                "DatierungArchivis": archivis_date_value(data["datierung"]),
                "Korrespondenzstueck": yes_no_empty(data.get("korrespondenzstueck")),
                "Herkunft": erschliessung.get("herkunft") or "",
                "Sammler": erschliessung.get("sammler") or "",
                "Fotograf": erschliessung.get("fotograf") or "",
                "Rechteinhaber": erschliessung.get("rechteinhaber") or "",
                "Orte": "; ".join(erschliessung.get("orte") or []),
                "Schlagworte": "; ".join(erschliessung.get("schlagworte") or []),
                "Altsignatur": "; ".join(erschliessung.get("altsignaturen") or []),
                "InterneBemerkung": erschliessung.get("interne_bemerkung") or "",
            }
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
