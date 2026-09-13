"""Photo compatibility checks; never enable GitHub writes."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from backend.github.repository import InMemoryGitRepository
from backend.modules import get_module
from backend.records.generic_write import create_generic_record
from integration_tests.photo_fixture import MODULE_KEY, STATE_PATH, sample_payload, server_defaults
from integration_tests.photo_github import PhotoRepository, compare_legacy


class GenericPhotoCompatibilityTest(unittest.TestCase):
    def test_all_partitions_match_legacy_canonical_creation(self):
        module = get_module(MODULE_KEY)
        user = SimpleNamespace(username="foto-test-redaktion", role="redaktion")
        initial = {"next_record_id": 10332, "next_signature_number": dict(zip("ABCDEF", (8610, 1046, 579, 81, 36, 1)))}
        for partition in "ABCDEF":
            with self.subTest(partition=partition):
                repository = InMemoryGitRepository({STATE_PATH: json.dumps(initial)})
                payload = sample_payload(partition)
                stored = create_generic_record(repository, module, payload, user, server_defaults(module, user, payload))
                record = compare_legacy(repository, stored.path, payload, initial)
                self.assertEqual(record["id"], "foto-010332")
                self.assertEqual(record["signatur"]["anzeige"], f"9.4.2.{partition}.{initial['next_signature_number'][partition]}")
                self.assertEqual(len(record["erschliessung"]["dargestellte_personen"]), 2)
                self.assertEqual(record["datierung"], payload["datierung"])
                expected = deepcopy(initial)
                expected["next_record_id"] += 1
                expected["next_signature_number"][partition] += 1
                self.assertEqual(json.loads(repository.files[STATE_PATH]), expected)
                self.assertEqual(set(repository.commits[-1]["files"]), {STATE_PATH, stored.path})

    def test_photo_guard_only_allows_selected_new_record(self):
        repository = object.__new__(PhotoRepository)
        repository.allowed_record_path = "data/fotos/foto-010332.md"
        repository.check_files({repository.allowed_record_path: "x", STATE_PATH: "{}"})
        repository.check_files({repository.allowed_record_path: "x"})
        for files in ({STATE_PATH: "{}"}, {"data/fotos/foto-000002.md": "x"}, {"indexes/fotos.json": "{}"},
                      {"data/fotos/foto-010333.md": "x"}):
            with self.subTest(files=files), self.assertRaises(RuntimeError):
                repository.check_files(files)

    def test_complete_http_photo_scenario_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            result = subprocess.run([sys.executable, "-m", "integration_tests.photo_github", "--offline", "--report", str(path)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            report = json.loads(path.read_text())
            self.assertEqual(report["result"], "passed")
            self.assertEqual(report["update_conflict"]["stale_status"], 409)
            self.assertEqual(report["state_after"]["next_record_id"], 10333)
            self.assertEqual(report["state_after"]["next_signature_number"]["A"], 8611)
            self.assertIn("direct ID read 200", report["index"])
