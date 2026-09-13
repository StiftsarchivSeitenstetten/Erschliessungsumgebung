"""Offline coverage of the opt-in runner and its write boundaries."""

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from backend.config import Settings
from integration_tests.generic_github import GuardedRepository, check_paths, check_target


class GenericIntegrationSafetyTest(unittest.TestCase):
    def test_target_rejects_main_other_repository_and_ambiguous_branch(self):
        valid = Settings(database_url="sqlite://", cookie_secure=False, github_data_branch="integration-test")
        check_target(valid)
        for kwargs in ({"github_data_branch": "main"}, {"github_data_branch": "integration-test "},
                       {"github_data_repo": "other"}, {"github_data_owner": "other"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(RuntimeError):
                check_target(replace(valid, **kwargs))

    def test_paths_reject_photo_state_and_traversal(self):
        check_paths({"data/integration-test/integration-0001.md": "x", "state/integration-test.json": "{}"})
        for path in ("data/fotos/foto-000001.md", "state/foto-papierabzuege.json",
                     "data/integration-test/../fotos/foto-000001.md", "indexes/fotos.json"):
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                check_paths({path: "x"})

    def test_low_level_guard_rejects_main_ref_and_force_without_network(self):
        repository = object.__new__(GuardedRepository)
        repository.settings = Settings(database_url="sqlite://", cookie_secure=False, github_data_branch="integration-test")
        with patch.object(repository, "guard"), patch("backend.github.github_repository.GitHubDataRepository.request") as network:
            with self.assertRaises(RuntimeError):
                repository.request("PATCH", repository.repo_path + "/git/refs/heads/main", {"sha": "x", "force": False})
            with self.assertRaises(RuntimeError):
                repository.request("PATCH", repository.repo_path + "/git/refs/heads/integration-test", {"sha": "x", "force": True})
            network.assert_not_called()

    def test_complete_http_scenario_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            result = subprocess.run([sys.executable, "-m", "integration_tests.generic_github", "--offline", "--report", str(report)],
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            data = json.loads(report.read_text())
            self.assertEqual(data["result"], "passed")
            self.assertEqual([record["id"] for record in data["records"]], ["integration-0001", "integration-0002"])
            self.assertEqual(data["final_state"], {"next_record_id": 3, "next_signature_number": {"T": 3}})
            self.assertEqual(data["rejected"]["stale_revision"], 409)

    def test_live_runner_requires_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {"GENERIC_GITHUB_INTEGRATION": "0"}):
            result = subprocess.run([sys.executable, "-m", "integration_tests.generic_github", "--write", "--report", str(Path(directory) / "report.json")],
                                    capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("GENERIC_GITHUB_INTEGRATION=1", result.stderr)
