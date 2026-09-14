"""Generic index semantics, transactional writes and role-safe queries."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.github.errors import RepositoryConflictError, RepositoryError
from backend.github.repository import InMemoryGitRepository
from backend.modules import get_module, load_module
from backend.records.generic_write import create_generic_record, update_generic_record, render_record_content
from backend.records.module_index import (
    IndexPlan, blob_revision, build_index_entry, build_module_index, dump_index, make_index,
    natural_key, normalized_text, query_index, read_module_index, rebuild_module_index,
)
from backend.records.runtime import RecordPermissionError, RecordValidationError
from backend.routes import modules as routes
from backend.routes.deps import require_authenticated_user
from tests.test_record_runtime import valid_payload, write_runtime_module, write_runtime_schema


class ModuleIndexTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        original = load_module(write_runtime_module(root, write_runtime_schema(root)))
        search = {"fulltext": ["daten.name", "daten.secret", "daten.agent", "daten.place", "daten.date",
                               "daten.date_range", "daten.term", "daten.identifier", "daten.language", "daten.beteiligte.name"],
                  "lookup": ["daten.identifier.value", "daten.secret"], "filters": [{"path": "daten.language"}]}
        self.module = replace(original, storage={**original.storage, "index": {"path": "indexes/runtime.json"}},
                              search_config=search, list_config={"columns": [
                                  {"path": "daten.name"}, {"path": "daten.secret"}, {"path": "daten.date_range"}],
                                  "default_sort": {"path": "daten.name", "direction": "asc"}})
        self.repo = InMemoryGitRepository({
            "state/runtime-test.json": json.dumps({"next_record_id": 1, "next_signature_number": {"A": 1}}),
            "indexes/runtime.json": dump_index(make_index(self.module, [])),
        })
        self.user = SimpleNamespace(username="rita", role="redaktion", modules=["runtime_test"])
        self.payload = valid_payload()
        self.payload["daten"]["secret"] = "NurRedaktionGeheim"

    def create(self):
        return create_generic_record(self.repo, self.module, self.payload, self.user)

    def test_structured_types_and_configured_paths_only(self):
        record = self.create().data
        entry = build_index_entry(self.module, record, "rev")
        self.assertEqual(entry["values"]["daten.beteiligte.name"], ["A", "B"])
        self.assertEqual(entry["lookup"]["daten.identifier.value"], "alt-1")
        for path, term in (("daten.agent", "muster, maria"), ("daten.place", "seitenstetten"),
                           ("daten.date", "1900"), ("daten.date_range", "1901"), ("daten.term", "brief"),
                           ("daten.identifier", "alt-1"), ("daten.language", "de")):
            self.assertIn(term, entry["search"][path])
        self.assertNotIn("daten.asset", entry["values"])
        self.assertNotIn("technik", entry["values"])
        self.assertEqual(normalized_text(None), "")
        self.assertEqual(normalized_text("  STRASSE\n  Test "), "strasse test")
        self.assertIn("1967-06-13", normalized_text({"jahr": 1967, "monat": 6, "tag": 13}))
        self.assertIn("1900-02", normalized_text({"from": {"year": 1900, "month": 2}, "display": "Februar"}))

    def test_rebuild_idempotent_and_same_as_incremental(self):
        self.create()
        before = self.repo.files["indexes/runtime.json"]
        commits = len(self.repo.commits)
        rebuilt = rebuild_module_index(self.repo, self.module)
        self.assertEqual(dump_index(rebuilt), before)
        rebuild_module_index(self.repo, self.module)
        self.assertEqual(len(self.repo.commits), commits)
        self.repo.files["indexes/runtime.json"] = "broken"
        rebuild_module_index(self.repo, self.module)
        self.assertEqual(self.repo.files["indexes/runtime.json"], before)

    def test_embedded_dashes_do_not_terminate_frontmatter(self):
        self.payload["daten"]["name"] = "63.---, 64. Test"
        stored = self.create()
        index = build_module_index(self.module, [self.repo.read_file(stored.path)])
        self.assertEqual(index["records"][0]["values"]["daten.name"], "63.---, 64. Test")
        self.assertEqual(dump_index(index), self.repo.files["indexes/runtime.json"])

    def test_create_update_revision_and_atomic_files(self):
        stored = self.create()
        self.assertEqual(set(self.repo.commits[-1]["files"]), {stored.path, "state/runtime-test.json", "indexes/runtime.json"})
        entry = read_module_index(self.repo, self.module)["records"][0]
        self.assertEqual(entry["revision"], stored.revision)
        state = self.repo.files["state/runtime-test.json"]
        changed = deepcopy(self.payload)
        changed["daten"]["name"] = "Geaendert"
        updated = update_generic_record(self.repo, self.module, stored.record_id, changed, stored.revision, self.user)
        self.assertEqual(set(self.repo.commits[-1]["files"]), {stored.path, "indexes/runtime.json"})
        self.assertEqual(self.repo.files["state/runtime-test.json"], state)
        entry = read_module_index(self.repo, self.module)["records"][0]
        self.assertEqual(entry["revision"], updated.revision)
        self.assertEqual(entry["values"]["daten.name"], "Geaendert")
        self.assertEqual(dump_index(build_module_index(self.module, [self.repo.read_file(stored.path)])), self.repo.files["indexes/runtime.json"])

    def test_failures_leave_all_files_unchanged(self):
        before = deepcopy(self.repo.files)
        for extra in ({"unknown": "x"}, {"readonly": "x"}):
            unauthorized = valid_payload()
            unauthorized["daten"].update(extra)
            with self.assertRaises(RecordPermissionError):
                create_generic_record(self.repo, self.module, unauthorized, SimpleNamespace(username="anna", role="ehrenamtlich"))
            self.assertEqual(self.repo.files, before)
        bad = deepcopy(self.payload)
        bad["daten"]["name"] = None
        with self.assertRaises(RecordValidationError):
            create_generic_record(self.repo, self.module, bad, self.user)
        self.assertEqual(self.repo.files, before)
        self.repo._conflict_failures = 1
        with self.assertRaises(RepositoryConflictError):
            self.create()
        self.assertEqual(self.repo.files, before)
        with patch("backend.records.module_index.build_index_entry", side_effect=RepositoryError("Indexfehler")):
            with self.assertRaises(RepositoryError):
                self.create()
        self.assertEqual(self.repo.files, before)
        invalid = replace(self.module, search_config={"fulltext": ["daten.does_not_exist"]})
        with self.assertRaises(RecordValidationError):
            create_generic_record(self.repo, invalid, self.payload, self.user)
        self.assertEqual(self.repo.files, before)
        self.repo.files["data/test/test-0001.md"] = "occupied"
        before = deepcopy(self.repo.files)
        with self.assertRaises(RepositoryConflictError):
            self.create()
        self.assertEqual(self.repo.files, before)

    def test_update_conflicts_do_not_change_index(self):
        stored = self.create()
        before = deepcopy(self.repo.files)
        for revision, external in (("stale", False), (stored.revision, True)):
            self.repo._conflict_failures = int(external)
            with self.assertRaises(RepositoryConflictError):
                update_generic_record(self.repo, self.module, stored.record_id, self.payload, revision, self.user)
            self.assertEqual(self.repo.files, before)
        with patch("backend.records.module_index.build_index_entry", side_effect=RepositoryError("Indexfehler")):
            with self.assertRaises(RepositoryError):
                update_generic_record(self.repo, self.module, stored.record_id, self.payload, stored.revision, self.user)
        self.assertEqual(self.repo.files, before)

    def test_index_cannot_overwrite_state_and_invalid_record_aborts_rebuild(self):
        invalid = replace(self.module, storage={**self.module.storage, "index": {"path": "state/runtime-test.json"}})
        before = deepcopy(self.repo.files)
        with self.assertRaises(RecordValidationError):
            create_generic_record(self.repo, invalid, self.payload, self.user)
        self.assertEqual(self.repo.files, before)
        self.repo.files["data/test/test-0099.md"] = "---\nid: test-0099\n---\n"
        before = deepcopy(self.repo.files)
        with self.assertRaises(RecordValidationError):
            rebuild_module_index(self.repo, self.module)
        self.assertEqual(self.repo.files, before)

    def test_casefold_multi_field_search_lookup_and_natural_sort(self):
        self.create()
        self.payload["daten"]["name"] = "Test 10"
        self.create()
        self.payload["daten"]["name"] = "Test 2"
        self.create()
        index = read_module_index(self.repo, self.module)
        results = query_index(self.module, index, "redaktion", q="MARIA Seitenstetten 1901")
        self.assertEqual([item["record_id"] for item in results], ["test-0001", "test-0003", "test-0002"])
        self.assertEqual(len(query_index(self.module, index, "redaktion", lookup_field="daten.identifier.value", lookup_value="ALT-1")), 3)
        self.assertEqual(sorted(["X.10", "X.2", "X.2a"], key=natural_key), ["X.2", "X.2a", "X.10"])

    def test_http_role_filter_prevents_hidden_hits_and_directory_reads(self):
        self.create()
        app = FastAPI()
        app.include_router(routes.router)
        app.state.data_repository = self.repo
        app.dependency_overrides[require_authenticated_user] = lambda: self.user
        self.user.role = "ehrenamtlich"
        with patch("backend.routes.modules.get_module", return_value=self.module), TestClient(app) as client:
            self.repo.read_file_calls.clear()
            self.repo.list_directory_calls.clear()
            url = "/api/modules/runtime_test/records"
            result = client.get(url)
            self.assertEqual(result.status_code, 200)
            self.assertNotIn("daten.secret", result.json()["records"][0]["values"])
            self.assertEqual(client.get(url, params={"q": "NurRedaktionGeheim"}).json()["records"], [])
            self.assertNotEqual(client.get(url, params={"lookup_field": "daten.secret", "lookup_value": "NurRedaktionGeheim"}).status_code, 200)
            self.assertEqual(set(self.repo.read_file_calls), {"indexes/runtime.json"})
            self.assertEqual(self.repo.list_directory_calls, [])
            self.user.role = "redaktion"
            self.assertEqual(len(client.get(url, params={"q": "NurRedaktionGeheim"}).json()["records"]), 1)

    def test_photo_entry_uses_same_engine(self):
        from integration_tests.photo_fixture import sample_payload, server_defaults
        module = get_module("foto_papierabzuege")
        repo = InMemoryGitRepository({"state/foto-papierabzuege.json": json.dumps({"next_record_id": 1, "next_signature_number": {"A": 2}}),
                                     module.storage["index"]["path"]: dump_index(make_index(module, []))})
        payload = sample_payload()
        stored = create_generic_record(repo, module, payload, self.user, server_defaults(module, self.user, payload))
        results = query_index(module, read_module_index(repo, module), "ehrenamtlich", lookup_field="signatur.anzeige", lookup_value="9.4.2.A.2")
        self.assertEqual(results[0]["record_id"], stored.record_id)
