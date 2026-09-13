#!/usr/bin/env python3
"""Validate photo Markdown records."""

from __future__ import annotations

from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from backend.modules import list_modules, validate_core_schemas
from foto_core import load_records, validate_collection


def main() -> int:
    try:
        validate_core_schemas()
        modules = list_modules()
    except Exception as exc:
        print(f"Modulkonfiguration ungueltig: {exc}", file=sys.stderr)
        return 1
    data_dir = repo_root / "data" / "fotos"
    records = load_records(data_dir)
    errors = validate_collection(records)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: {len(records)} Foto-Datensaetze validiert; {len(modules)} Modulkonfiguration(en) validiert")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
