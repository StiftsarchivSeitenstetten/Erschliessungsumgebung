from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from openpyxl import Workbook

from backend.github.errors import RepositoryConflictError
from backend.github.repository import InMemoryGitRepository
from backend.migration.autographen.apply_migration1 import (
    ApplyConfiguration,
    ApplySafetyError,
    COMMIT_MESSAGE,
    CONFIRMATION,
    PREFLIGHT_SUCCESS,
    build_preflight,
    perform_apply,
    write_preflight_reports,
)
from backend.migration.autographen.migration1 import IGNORED_EXPORT_COLUMNS, REQUIRED_COLUMNS
from backend.modules import get_module
from backend.records.generic_read import parse_record_file
from backend.records.module_index import dump_index, make_index, read_module_index
from backend.records.runtime import RecordRuntime


class AutographMigration1ApplyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "fixture.xlsm"
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        (self.artifacts / "errors.json").write_text("[]\n", encoding="utf-8")
        (self.artifacts / "qa_report.md").write_text(
            "MIGRATION 1 FACHLICH UND TECHNISCH ZUM APPLY FREIGEGEBEN.\n",
            encoding="utf-8",
        )
        self._write_source()
        self.source_hash = sha256(self.source.read_bytes()).hexdigest()
        self.configuration = ApplyConfiguration(
            expected_source_sha256=self.source_hash,
            expected_data_head="data-head",
            required_signatures=("9.6.1", "9.6.2"),
            expected_record_count=2,
        )
        self.module = get_module("autographen_9_6")
        self.state_path = self.module.storage["state"]["path"]
        self.index_path = self.module.storage["index"]["path"]
        self.state_content = json.dumps({
            "next_record_id": 265,
            "next_signature_number": {"A": 263},
            "create_operations": {},
        }, ensure_ascii=False, indent=2) + "\n"

    def _write_source(self):
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Autographen"
        headers = [*REQUIRED_COLUMNS, *IGNORED_EXPORT_COLUMNS]
        sheet.append(headers)
        for number in (1, 2):
            values = {column: None for column in headers}
            values.update({
                "Signatur": f"9.6.{number}",
                "Kategorie": "Brief",
                "Schreiber": f"Schreiber {number}",
                "Empfaenger": f"Empfänger {number}",
                "Datierung": f"190{number}0102",
                "Ort": "Wien",
                "Regest": f"Regest {number}",
                "Olim": f"Alt {number}",
            })
            sheet.append([values[column] for column in headers])
        workbook.save(self.source)

    def repository(self) -> InMemoryGitRepository:
        repository = InMemoryGitRepository({
            self.state_path: self.state_content,
            self.index_path: dump_index(make_index(self.module, [])),
        })
        repository.head = "data-head"
        return repository

    def preflight(self, repository=None):
        return build_preflight(
            repository or self.repository(),
            self.source,
            self.artifacts,
            configuration=self.configuration,
            repository_name="test/data",
            branch="main",
            code_commit="code-test",
        )

    def approve(self, repository):
        result = self.preflight(repository)
        write_preflight_reports(result, self.artifacts)
        return result

    def apply(self, repository, confirmation=CONFIRMATION):
        return perform_apply(
            repository,
            self.source,
            self.artifacts,
            confirmation,
            configuration=self.configuration,
            repository_name="test/data",
            branch="main",
            code_commit="code-test",
        )

    def test_successful_preflight_is_read_only_and_complete(self):
        repository = self.repository()
        before = deepcopy(repository.files)
        result = self.preflight(repository)

        self.assertEqual(repository.files, before)
        self.assertEqual(repository.commits, [])
        self.assertEqual(result.report["status"], PREFLIGHT_SUCCESS)
        self.assertEqual(result.report["existing_production_records"], 0)
        self.assertEqual(result.report["planned_records"], 2)
        self.assertEqual(result.report["planned_files_total"], 3)
        self.assertFalse(result.report["state_will_be_written"])
        self.assertEqual(result.report["planned_repository_commits"], 1)
        self.assertEqual(len(result.plan.fingerprint), 64)
        self.assertEqual(set(result.plan.files), {
            "data/autographen/autograph-000001.md",
            "data/autographen/autograph-000002.md",
            self.index_path,
        })

    def test_wrong_source_hash_aborts_without_repository_write(self):
        repository = self.repository()
        wrong = ApplyConfiguration(
            expected_source_sha256="0" * 64,
            expected_data_head="data-head",
            required_signatures=self.configuration.required_signatures,
            expected_record_count=2,
        )
        with self.assertRaisesRegex(ApplySafetyError, "SHA-256"):
            build_preflight(repository, self.source, self.artifacts, configuration=wrong, code_commit="test")
        self.assertEqual(repository.commits, [])

    def test_wrong_head_aborts(self):
        repository = self.repository()
        repository.head = "parallel-head"
        with self.assertRaisesRegex(ApplySafetyError, "Datenbranch-Head"):
            self.preflight(repository)
        self.assertEqual(repository.commits, [])

    def test_existing_record_or_target_path_aborts(self):
        for path in ("data/autographen/other.md", "data/autographen/autograph-000001.md"):
            with self.subTest(path=path):
                repository = self.repository()
                repository.files[path] = "occupied"
                with self.assertRaisesRegex(ApplySafetyError, "nicht leer"):
                    self.preflight(repository)
                self.assertEqual(repository.commits, [])

    def test_nonempty_index_aborts(self):
        repository = self.repository()
        plan = self.preflight(repository).plan
        repository.files[self.index_path] = plan.files[self.index_path]
        with self.assertRaisesRegex(ApplySafetyError, "Modulindex ist nicht leer"):
            self.preflight(repository)

    def test_invalid_state_values_abort(self):
        cases = (
            ({"next_record_id": 266, "next_signature_number": {"A": 263}, "create_operations": {}}, "next_record_id"),
            ({"next_record_id": 265, "next_signature_number": {"A": 264}, "create_operations": {}}, "next_signature_number"),
            ({"next_record_id": 265, "next_signature_number": {"A": 263}, "create_operations": {"x": {}}}, "create_operations"),
        )
        for state, message in cases:
            with self.subTest(message=message):
                repository = self.repository()
                repository.files[self.state_path] = json.dumps(state)
                with self.assertRaisesRegex(ApplySafetyError, message):
                    self.preflight(repository)
                self.assertEqual(repository.commits, [])

    def test_schema_and_vocabulary_errors_abort(self):
        for error_type in ("schema", "vocabulary"):
            with self.subTest(error_type=error_type):
                repository = self.repository()
                error = {
                    "error_type": error_type,
                    "message": f"forced {error_type} error",
                }
                with patch(
                    "backend.migration.autographen.apply_migration1.validate_record",
                    return_value=[error],
                ):
                    with self.assertRaisesRegex(ApplySafetyError, f"forced {error_type} error"):
                        self.preflight(repository)
                self.assertEqual(repository.commits, [])

    def test_apply_requires_exact_confirmation(self):
        repository = self.repository()
        self.approve(repository)
        for confirmation in (None, "yes", CONFIRMATION + "-X"):
            with self.subTest(confirmation=confirmation):
                with self.assertRaisesRegex(ApplySafetyError, "--confirm"):
                    self.apply(repository, confirmation)
        self.assertEqual(repository.commits, [])

    def test_changed_plan_fingerprint_aborts(self):
        repository = self.repository()
        self.approve(repository)
        report_path = self.artifacts / "apply_preflight.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["plan_fingerprint_sha256"] = "f" * 64
        report_path.write_text(json.dumps(report), encoding="utf-8")
        with self.assertRaisesRegex(ApplySafetyError, "Schreibplan"):
            self.apply(repository)
        self.assertEqual(repository.commits, [])

    def test_changed_code_commit_aborts(self):
        repository = self.repository()
        self.approve(repository)
        with self.assertRaisesRegex(ApplySafetyError, "Code-Commit"):
            perform_apply(
                repository,
                self.source,
                self.artifacts,
                CONFIRMATION,
                configuration=self.configuration,
                repository_name="test/data",
                branch="main",
                code_commit="different-code",
            )
        self.assertEqual(repository.commits, [])

    def test_head_change_between_preflight_and_commit_aborts_atomically(self):
        repository = self.repository()
        self.approve(repository)
        before = deepcopy(repository.files)
        repository._conflict_failures = 1
        with self.assertRaises(RepositoryConflictError):
            self.apply(repository)
        self.assertEqual(repository.files, before)
        self.assertEqual(repository.commits, [])

    def test_successful_apply_is_one_commit_records_and_index_without_state(self):
        repository = self.repository()
        state_before = repository.read_file(self.state_path)
        approved = self.approve(repository)
        verification = self.apply(repository)

        self.assertEqual(len(repository.commits), 1)
        commit = repository.commits[0]
        self.assertEqual(commit["message"], COMMIT_MESSAGE)
        self.assertEqual(commit["parent"], "data-head")
        self.assertEqual(len(commit["files"]), 3)
        self.assertNotIn(self.state_path, commit["files"])
        self.assertEqual(repository.read_file(self.state_path), state_before)
        self.assertEqual(verification["records"], 2)
        self.assertEqual(verification["index_records"], 2)
        self.assertTrue(verification["record_index_consistent"])
        self.assertTrue(verification["content_matches_plan"])
        index = read_module_index(repository, self.module)
        self.assertEqual([entry["record_id"] for entry in index["records"]], ["autograph-000001", "autograph-000002"])
        runtime = RecordRuntime(self.module, repository)
        for path in approved.plan.record_paths:
            record = parse_record_file(repository.read_file(path)).data
            runtime.validate(record)
            runtime.validate_vocabulary_references(record)
        self.assertTrue((self.artifacts / "apply_report.json").exists())
        self.assertTrue((self.artifacts / "apply_report.md").exists())

    def test_second_apply_attempt_aborts(self):
        repository = self.repository()
        self.approve(repository)
        self.apply(repository)
        with self.assertRaisesRegex(ApplySafetyError, "Datenbranch-Head"):
            self.apply(repository)
        self.assertEqual(len(repository.commits), 1)

    def test_apply_module_has_no_normal_create_or_rest_write_path(self):
        source = Path("backend/migration/autographen/apply_migration1.py").read_text(encoding="utf-8")
        self.assertNotIn("create_generic_record", source)
        self.assertNotIn("requests.post", source)
        self.assertNotIn("requests.put", source)
        self.assertEqual(source.count("repository.commit_files("), 1)


if __name__ == "__main__":
    unittest.main()
