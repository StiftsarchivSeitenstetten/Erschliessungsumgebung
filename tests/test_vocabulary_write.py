import json
from pathlib import Path
import unittest

import yaml

from backend.github.errors import RepositoryConflictError
from backend.github.repository import InMemoryGitRepository
from backend.vocabularies import (
    VocabularyPermissionError,
    VocabularyRevisionConflictError,
    VocabularyTermExistsError,
    VocabularyTermNotFound,
    VocabularyValidationError,
    add_term,
    deactivate_term,
    read_repository_vocabulary,
    rename_term,
)


ROOT = Path(__file__).resolve().parents[1]
PATH = "vocabularies/dokumenttypen.yaml"


def vocabulary_content(**rights) -> str:
    raw = yaml.safe_load((ROOT / PATH).read_text(encoding="utf-8"))
    if rights:
        raw["rights"] = rights
    return yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)


class VocabularyWriteServiceTest(unittest.TestCase):
    def setUp(self):
        self.repository = InMemoryGitRepository({PATH: vocabulary_content()})
        self.revision = self.repository.read_file(PATH).revision

    def test_add_rename_deactivate_preserve_ids_and_return_blob_revisions(self):
        added = add_term(
            self.repository, PATH, "dokumenttypen", self.revision, "redaktion",
            {"id": "tagebuch", "label": "Tagebuch", "active": True, "aliases": ["Journal"]},
        )
        self.assertNotEqual(added.revision, self.revision)
        self.assertNotEqual(added.revision, self.repository.get_branch_head())
        self.assertEqual(added.vocabulary.resolve("tagebuch").label, "Tagebuch")

        renamed = rename_term(
            self.repository, PATH, "dokumenttypen", added.revision, "redaktion", "tagebuch", "Journal",
        )
        self.assertEqual(renamed.vocabulary.resolve("tagebuch").id, "tagebuch")
        self.assertEqual(renamed.vocabulary.resolve("tagebuch").label, "Journal")
        self.assertEqual(renamed.vocabulary.resolve("tagebuch").aliases, ("Journal",))

        deactivated = deactivate_term(
            self.repository, PATH, "dokumenttypen", renamed.revision, "redaktion", "tagebuch",
        )
        self.assertFalse(deactivated.vocabulary.resolve("tagebuch").active)
        read_back = read_repository_vocabulary(self.repository, PATH, "dokumenttypen")
        self.assertFalse(read_back.vocabulary.resolve("tagebuch").active)
        self.assertEqual(len(self.repository.commits), 3)
        self.assertTrue(all(commit["files"] == [PATH] for commit in self.repository.commits))

    def test_stale_concrete_revision_conflicts_without_write(self):
        first = rename_term(
            self.repository, PATH, "dokumenttypen", self.revision, "redaktion", "brief", "Schreiben",
        )
        commits = len(self.repository.commits)
        with self.assertRaises(VocabularyRevisionConflictError):
            deactivate_term(self.repository, PATH, "dokumenttypen", self.revision, "redaktion", "brief")
        self.assertEqual(len(self.repository.commits), commits)
        self.assertTrue(first.vocabulary.resolve("brief").active)

    def test_unrelated_branch_conflict_is_retried_against_same_blob_revision(self):
        repository = InMemoryGitRepository({PATH: vocabulary_content()}, conflict_failures=1)
        revision = repository.read_file(PATH).revision
        stored = rename_term(repository, PATH, "dokumenttypen", revision, "redaktion", "brief", "Schreiben")
        self.assertEqual(stored.vocabulary.label_for("brief"), "Schreiben")
        self.assertEqual(len(repository.commits), 1)

    def test_duplicate_unknown_permission_and_validation_fail_without_commit(self):
        with self.assertRaises(VocabularyTermExistsError):
            add_term(
                self.repository, PATH, "dokumenttypen", self.revision, "redaktion",
                {"id": "brief", "label": "Anders", "active": True},
            )
        with self.assertRaises(VocabularyTermNotFound):
            rename_term(self.repository, PATH, "dokumenttypen", self.revision, "redaktion", "fehlt", "Neu")
        with self.assertRaises(VocabularyTermNotFound):
            deactivate_term(self.repository, PATH, "dokumenttypen", self.revision, "redaktion", "fehlt")
        with self.assertRaises(VocabularyPermissionError):
            add_term(
                self.repository, PATH, "dokumenttypen", self.revision, "ehrenamtlich",
                {"id": "neu", "label": "Neu", "active": True},
            )
        with self.assertRaises(VocabularyValidationError):
            rename_term(self.repository, PATH, "dokumenttypen", self.revision, "redaktion", "brief", "   ")
        with self.assertRaises(VocabularyValidationError):
            add_term(
                self.repository, PATH, "dokumenttypen", self.revision, "redaktion",
                {"id": "neu", "label": "Neu", "active": True, "unknown": "x"},
            )
        with self.assertRaises(VocabularyValidationError):
            add_term(
                self.repository, PATH, "dokumenttypen", "", "redaktion",
                {"id": "neu", "label": "Neu", "active": True},
            )
        self.assertEqual(self.repository.commits, [])

    def test_each_operation_uses_its_declarative_permission(self):
        repository = InMemoryGitRepository({PATH: vocabulary_content(
            use=["ehrenamtlich"], add=["ehrenamtlich"], rename=[], deactivate=[],
        )})
        revision = repository.read_file(PATH).revision
        added = add_term(
            repository, PATH, "dokumenttypen", revision, "ehrenamtlich",
            {"id": "neu", "label": "Neu", "active": True},
        )
        with self.assertRaises(VocabularyPermissionError):
            rename_term(repository, PATH, "dokumenttypen", added.revision, "ehrenamtlich", "neu", "Anders")
        with self.assertRaises(VocabularyPermissionError):
            deactivate_term(repository, PATH, "dokumenttypen", added.revision, "ehrenamtlich", "neu")

    def test_json_vocabulary_remains_json(self):
        path = "vocabularies/types.json"
        raw = yaml.safe_load(vocabulary_content())
        raw["id"] = "types"
        repository = InMemoryGitRepository({path: json.dumps(raw, ensure_ascii=False)})
        revision = repository.read_file(path).revision
        stored = add_term(
            repository, path, "types", revision, "redaktion",
            {"id": "notiz", "label": "Notiz", "active": True},
        )
        persisted = json.loads(repository.files[path])
        self.assertEqual(persisted["terms"][-1]["id"], "notiz")
        self.assertEqual(stored.vocabulary.label_for("notiz"), "Notiz")


if __name__ == "__main__":
    unittest.main()
