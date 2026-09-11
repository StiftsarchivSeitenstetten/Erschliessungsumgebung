#!/usr/bin/env python3
"""Validate photo Markdown records."""

from __future__ import annotations

from pathlib import Path
import sys

from foto_core import load_records, validate_collection


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    data_dir = repo_root / "data" / "fotos"
    records = load_records(data_dir)
    errors = validate_collection(records)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"OK: {len(records)} Foto-Datensaetze validiert")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
