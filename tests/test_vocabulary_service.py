from pathlib import Path
import tempfile
import unittest

import yaml

from backend.vocabularies import VocabularyError, VocabularyTermNotFound, load_vocabulary


ROOT = Path(__file__).resolve().parents[1]


class VocabularyServiceTest(unittest.TestCase):
    def tearDown(self):
        load_vocabulary.cache_clear()

    def test_loads_sorts_and_resolves_active_and_inactive_terms(self):
        vocabulary = load_vocabulary(ROOT / "vocabularies" / "dokumenttypen.yaml", "dokumenttypen")

        self.assertEqual(vocabulary.id, "dokumenttypen")
        self.assertEqual(vocabulary.label_for("brief"), "Brief")
        self.assertEqual(vocabulary.resolve("brief").aliases, ("Schreiben",))
        self.assertFalse(vocabulary.resolve("telefax").active)
        self.assertEqual([term.id for term in vocabulary.active_terms()], [
            "brief", "postkarte", "telegramm", "manuskript", "sonstiges",
        ])
        with self.assertRaises(VocabularyTermNotFound):
            vocabulary.resolve("unbekannt")

    def write(self, directory: str, data) -> Path:
        path = Path(directory) / "vocabulary.yaml"
        path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
        return path

    def test_rejects_invalid_schema_duplicate_ids_and_reference_mismatch(self):
        valid = {
            "id": "test", "label": "Test", "terms": [
                {"id": "a", "label": "A", "active": True},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(VocabularyError):
                load_vocabulary(self.write(directory, {"id": "test", "label": "Test", "terms": [{"id": "a"}]}))
            load_vocabulary.cache_clear()
            duplicate = {**valid, "terms": [valid["terms"][0], {"id": "a", "label": "Anders", "active": False}]}
            with self.assertRaises(VocabularyError):
                load_vocabulary(self.write(directory, duplicate))
            load_vocabulary.cache_clear()
            with self.assertRaises(VocabularyError):
                load_vocabulary(self.write(directory, valid), "andere_id")

    def test_second_vocabulary_uses_same_runtime(self):
        vocabulary = load_vocabulary(ROOT / "vocabularies" / "rollen.yaml", "rollen")
        self.assertEqual(vocabulary.label_for("empfaenger"), "Empfänger")
        self.assertFalse(vocabulary.resolve("erwaehnt").active)


if __name__ == "__main__":
    unittest.main()
