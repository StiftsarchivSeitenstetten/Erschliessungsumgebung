"""Load, validate and resolve small versioned controlled vocabularies."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from ..config import ROOT


VOCABULARY_SCHEMA_PATH = ROOT / "schemas" / "vocabulary.schema.json"


class VocabularyError(ValueError):
    pass


class VocabularyTermNotFound(VocabularyError):
    pass


class VocabularyValidationError(VocabularyError):
    pass


@dataclass(frozen=True)
class VocabularyTerm:
    id: str
    label: str
    active: bool
    description: str | None = None
    aliases: tuple[str, ...] = ()
    sort_order: int | None = None

    def descriptor(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "active": self.active,
            "description": self.description,
            "aliases": list(self.aliases),
            "sort_order": self.sort_order,
        }


@dataclass(frozen=True)
class Vocabulary:
    id: str
    label: str
    description: str | None
    terms: tuple[VocabularyTerm, ...]
    rights: dict[str, tuple[str, ...]]

    def resolve(self, term_id: str) -> VocabularyTerm:
        for term in self.terms:
            if term.id == term_id:
                return term
        raise VocabularyTermNotFound(f"Unbekannte Term-ID {term_id!r} in Vokabular {self.id!r}.")

    def label_for(self, term_id: str) -> str:
        return self.resolve(term_id).label

    def active_terms(self) -> tuple[VocabularyTerm, ...]:
        return tuple(term for term in self.terms if term.active)

    def allows(self, role: str, operation: str) -> bool:
        return role in self.rights.get(operation, ())

    def descriptor(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "terms": [term.descriptor() for term in self.terms],
        }


def parse_vocabulary(content: str, expected_id: str | None = None, source: str = "Vocabulary-Datei") -> tuple[Vocabulary, dict[str, Any]]:
    try:
        raw = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise VocabularyValidationError(f"{source} ist kein gueltiges YAML.") from exc
    if not isinstance(raw, dict):
        raise VocabularyValidationError(f"{source} ist kein Mapping.")
    schema = json.loads(VOCABULARY_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(instance=raw, schema=schema)
    except jsonschema.ValidationError as exc:
        raise VocabularyValidationError(f"Ungueltiges Vokabular {source}: {exc.message}") from exc
    if expected_id is not None and raw["id"] != expected_id:
        raise VocabularyValidationError(
            f"Vocabulary-ID {raw['id']!r} stimmt nicht mit Referenz {expected_id!r} ueberein."
        )
    ids = [term["id"] for term in raw["terms"]]
    duplicates = sorted({term_id for term_id in ids if ids.count(term_id) > 1})
    if duplicates:
        raise VocabularyValidationError(f"Doppelte Term-ID(s) in {raw['id']!r}: {', '.join(duplicates)}")
    terms = tuple(VocabularyTerm(
        id=term["id"],
        label=term["label"],
        active=term["active"],
        description=term.get("description"),
        aliases=tuple(term.get("aliases") or ()),
        sort_order=term.get("sort_order"),
    ) for term in _sorted_terms(raw["terms"]))
    rights = {
        operation: tuple(roles)
        for operation, roles in (raw.get("rights") or {}).items()
    }
    return Vocabulary(raw["id"], raw["label"], raw.get("description"), terms, rights), raw


def _sorted_terms(raw_terms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not any(term.get("sort_order") is not None for term in raw_terms):
        return raw_terms
    ordered = sorted(enumerate(raw_terms), key=lambda item: (
        item[1].get("sort_order") is None,
        item[1].get("sort_order") if item[1].get("sort_order") is not None else 0,
        item[0],
    ))
    return [item[1] for item in ordered]


@lru_cache(maxsize=64)
def load_vocabulary(path: str | Path, expected_id: str | None = None) -> Vocabulary:
    vocabulary_path = Path(path)
    if not vocabulary_path.exists():
        raise VocabularyError(f"Vocabulary-Datei fehlt: {vocabulary_path}")
    vocabulary, _ = parse_vocabulary(
        vocabulary_path.read_text(encoding="utf-8"), expected_id, str(vocabulary_path),
    )
    return vocabulary
