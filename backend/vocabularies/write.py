"""Repository-backed, optimistic writes for controlled vocabulary terms."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from typing import Any, Callable

import yaml

from ..github.errors import RepositoryConflictError
from ..github.repository import DataRepository
from .service import Vocabulary, VocabularyTermNotFound, VocabularyValidationError, parse_vocabulary


class VocabularyPermissionError(VocabularyValidationError):
    pass


class VocabularyRevisionConflictError(RepositoryConflictError):
    pass


class VocabularyTermExistsError(RepositoryConflictError):
    pass


@dataclass(frozen=True)
class StoredVocabulary:
    vocabulary: Vocabulary
    revision: str
    path: str
    raw: dict[str, Any]


def read_repository_vocabulary(
    repository: DataRepository, path: str, expected_id: str,
) -> StoredVocabulary:
    file = repository.read_file(path)
    vocabulary, raw = parse_vocabulary(file.content, expected_id, path)
    return StoredVocabulary(vocabulary, file.revision, file.path, raw)


def render_vocabulary(raw: dict[str, Any], path: str) -> str:
    if path.lower().endswith(".json"):
        return json.dumps(raw, ensure_ascii=False, indent=2) + "\n"
    return yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)


def _require_nonblank(value: str, field: str) -> None:
    if not value.strip():
        raise VocabularyValidationError(f"{field} darf nicht leer sein.")


def _mutate_add(raw: dict[str, Any], term: dict[str, Any]) -> None:
    _require_nonblank(term["id"], "Term-ID")
    _require_nonblank(term["label"], "Label")
    if any(existing["id"] == term["id"] for existing in raw["terms"]):
        raise VocabularyTermExistsError(f"Term-ID {term['id']!r} ist bereits vorhanden.")
    raw["terms"].append(deepcopy(term))


def _find_term(raw: dict[str, Any], term_id: str) -> dict[str, Any]:
    for term in raw["terms"]:
        if term["id"] == term_id:
            return term
    raise VocabularyTermNotFound(f"Unbekannte Term-ID {term_id!r} in Vokabular {raw['id']!r}.")


def _mutate_rename(raw: dict[str, Any], term_id: str, label: str) -> None:
    _require_nonblank(label, "Label")
    _find_term(raw, term_id)["label"] = label


def _mutate_deactivate(raw: dict[str, Any], term_id: str) -> None:
    _find_term(raw, term_id)["active"] = False


def write_vocabulary(
    repository: DataRepository,
    path: str,
    vocabulary_id: str,
    base_revision: str,
    role: str,
    operation: str,
    mutate: Callable[[dict[str, Any]], None],
) -> StoredVocabulary:
    if not base_revision:
        raise VocabularyValidationError("base_revision ist fuer Vocabulary-Write erforderlich.")

    # Retry only when an unrelated branch update raced with this write. A change
    # to the vocabulary blob itself is always returned as a concrete conflict.
    for _ in range(3):
        head = repository.get_branch_head()
        previous = read_repository_vocabulary(repository, path, vocabulary_id)
        if not previous.vocabulary.allows(role, operation):
            raise VocabularyPermissionError(f"Keine Berechtigung fuer Vocabulary-Operation {operation!r}.")
        if previous.revision != base_revision:
            raise VocabularyRevisionConflictError("Vokabular wurde zwischenzeitlich geaendert.")

        updated = deepcopy(previous.raw)
        mutate(updated)
        parse_vocabulary(render_vocabulary(updated, path), vocabulary_id, path)
        try:
            repository.commit_files(
                expected_head=head,
                files={path: render_vocabulary(updated, path)},
                message=f"Aktualisiere Vokabular {vocabulary_id}",
            )
        except RepositoryConflictError:
            latest = read_repository_vocabulary(repository, path, vocabulary_id)
            if latest.revision != base_revision:
                raise VocabularyRevisionConflictError("Vokabular wurde zwischenzeitlich geaendert.")
            continue
        return read_repository_vocabulary(repository, path, vocabulary_id)
    raise RepositoryConflictError("Repository wurde wiederholt parallel aktualisiert.")


def add_term(repository: DataRepository, path: str, vocabulary_id: str, base_revision: str, role: str, term: dict[str, Any]) -> StoredVocabulary:
    return write_vocabulary(
        repository, path, vocabulary_id, base_revision, role, "add",
        lambda raw: _mutate_add(raw, term),
    )


def rename_term(repository: DataRepository, path: str, vocabulary_id: str, base_revision: str, role: str, term_id: str, label: str) -> StoredVocabulary:
    return write_vocabulary(
        repository, path, vocabulary_id, base_revision, role, "rename",
        lambda raw: _mutate_rename(raw, term_id, label),
    )


def deactivate_term(repository: DataRepository, path: str, vocabulary_id: str, base_revision: str, role: str, term_id: str) -> StoredVocabulary:
    return write_vocabulary(
        repository, path, vocabulary_id, base_revision, role, "deactivate",
        lambda raw: _mutate_deactivate(raw, term_id),
    )
