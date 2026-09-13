"""The generic write routes are exercised only with an in-memory repository."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.auth.service import create_user
from backend.database import Base, SessionLocal, engine
from backend.github.errors import RepositoryError
from backend.github.repository import InMemoryGitRepository
from backend.main import create_app
from backend.models import ModuleAccess
from backend.modules import get_module, get_path_value, load_module, path_exists, set_path_value
from backend.permissions import MODULE_FOTO_PAPIERABZUEGE
from backend.records.generic_read import parse_record_content
from backend.records.generic_write import render_record_content
from scripts.foto_core import render_photo_markdown
from tests.test_record_runtime import valid_payload, write_runtime_module, write_runtime_schema
from tests.test_records_api import sample_record


class FailingRepository(InMemoryGitRepository):
    def commit_files(self, *, expected_head, files, message):
        raise RepositoryError("Test-Persistenzfehler")


class GenericWriteApiTest(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.test_module = load_module(write_runtime_module(root, write_runtime_schema(root)))
        self.real_get_module = get_module
        self.module_patch = patch(
            "backend.routes.modules.get_module",
            side_effect=lambda key: self.test_module if key == "runtime_test" else self.real_get_module(key),
        )
        self.module_patch.start()
        self.app = create_app()
        self.repo = InMemoryGitRepository()
        self.repo.files["state/runtime-test.json"] = json.dumps({"next_record_id": 1, "next_signature_number": {"A": 1}})
        self.repo.files["state/foto-papierabzuege.json"] = json.dumps({"next_record_id": 4, "next_signature_number": {"A": 7, "B": 1, "C": 1, "D": 1, "E": 1, "F": 1}})
        self.app.state.data_repository = self.repo
        self.app.state.generic_writes_enabled = True
        self.app.state.generic_server_values_provider = self.server_values
        self.client = TestClient(self.app)

    def tearDown(self):
        self.module_patch.stop()
        self.tmp.cleanup()

    def server_values(self, module, user, payload):
        if module.access_key == "runtime_test":
            return {}
        return {
            "schema_version": 1,
            "modul": module.id,
            "erschliessung.titel": None,
            "redaktion.stufe": "ehrenamtlich",
            "bearbeitung.status": "in_bearbeitung",
            "publikation.status": "intern",
        }

    def login(self, username="anna", role="ehrenamtlich", modules=None):
        if modules is None:
            modules = ["runtime_test"]
        with SessionLocal() as db:
            user = create_user(
                db,
                username=username,
                display_name=username.title(),
                email=f"{username}@example.test",
                role=role,
                ui_profile="ehrenamt-standard" if role == "ehrenamtlich" else "redaktion",
                modules=[MODULE_FOTO_PAPIERABZUEGE],
                password="SehrGeheim123",
            )
            if modules != [MODULE_FOTO_PAPIERABZUEGE]:
                user.module_access.clear()
                user.module_access.extend(ModuleAccess(module_key=key) for key in modules)
            db.commit()
        response = self.client.post("/api/auth/login", json={"login": username, "password": "SehrGeheim123"})
        self.assertEqual(response.status_code, 200)

    def csrf_headers(self):
        me = self.client.get("/api/auth/me").json()
        return {"X-CSRF-Token": self.client.cookies.get(me["csrf_cookie_name"])}

    def post(self, record=None, module="runtime_test", **transport):
        return self.client.post(
            f"/api/modules/{module}/records",
            json={"record": valid_payload() if record is None else record, **transport},
            headers=self.csrf_headers(),
        )

    def put(self, record_id, record, revision, module="runtime_test"):
        body = {"record": record}
        if revision is not None:
            body["base_revision"] = revision
        return self.client.put(
            f"/api/modules/{module}/records/{record_id}",
            json=body,
            headers=self.csrf_headers(),
        )

    def full_photo_payload(self, record, role="ehrenamtlich"):
        module = get_module("foto_papierabzuege")
        payload = {}
        for field in module.fields:
            if field.can_edit(role) and path_exists(record, field.path):
                set_path_value(payload, field.path, deepcopy(get_path_value(record, field.path)))
        return payload

    def test_create_runtime_module_sets_metadata_and_returns_filtered_record(self):
        self.login()
        response = self.post()
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()
        self.assertEqual(data["module"], "runtime_test")
        self.assertEqual(data["record_id"], "test-0001")
        self.assertEqual(data["record"]["id"], "test-0001")
        self.assertNotIn("technik", data["record"])
        self.assertTrue(data["meta"]["revision"])
        stored = parse_record_content(self.repo.files["data/test/test-0001.md"])
        self.assertEqual(stored["daten"]["agent"]["name"], "Muster, Maria")
        self.assertEqual(stored["daten"]["date_range"]["from"]["year"], 1900)
        self.assertEqual(stored["daten"]["term"]["id"], "brief")
        self.assertEqual(stored["technik"]["erstellt_von"], "anna")
        self.assertIsNotNone(stored["technik"]["erstellt_am"])
        self.assertIsNone(stored["technik"]["geaendert_am"])
        self.assertIsNone(stored["technik"]["geaendert_von"])
        self.assertEqual(self.repo.commits[0]["files"], ["data/test/test-0001.md", "state/runtime-test.json"])
        self.assertEqual(stored["signatur"]["anzeige"], "T.1")

    def test_create_rejects_bad_schema_and_unauthorized_fields_without_commit(self):
        self.login()
        cases = [
            ({"daten": {**valid_payload()["daten"], "name": None}}, 422),
            ({"daten": {key: value for key, value in valid_payload()["daten"].items() if key != "name"}}, 422),
            ({"daten": {**valid_payload()["daten"], "beteiligte": [{"rolle": "x"}]}}, 422),
            ({"daten": {**valid_payload()["daten"], "agent": {"type": "person"}}}, 422),
            ({"daten": {**valid_payload()["daten"], "unknown": "x"}}, 422),
            ({"daten": {**valid_payload()["daten"], "readonly": "x"}}, 403),
            ({"daten": {**valid_payload()["daten"], "secret": "x"}}, 403),
            ({**valid_payload(), "id": "client-id"}, 403),
            ({**valid_payload(), "technik": {"erstellt_von": "client"}}, 403),
            ({**valid_payload(), "base_revision": "in-record"}, 403),
        ]
        for payload, expected in cases:
            with self.subTest(payload=payload):
                self.assertEqual(self.post(payload).status_code, expected)
                self.assertEqual(self.repo.commits, [])
                self.assertEqual(json.loads(self.repo.files["state/runtime-test.json"])["next_record_id"], 1)

    def test_create_auth_module_access_and_optional_defaults(self):
        unauthenticated = self.client.post("/api/modules/runtime_test/records", json={"record": valid_payload()})
        self.assertEqual(unauthenticated.status_code, 401)
        self.login(modules=[])
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(self.post(module="unbekannt").status_code, 404)
        self.assertEqual(self.repo.commits, [])

        self.app.state.generic_server_values_provider = None
        self.login(username="rita", role="redaktion")
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(len(self.repo.commits), 1)

    def test_create_ref_conflict_and_consecutive_ids(self):
        self.login()
        self.repo._conflict_failures = 1
        self.assertEqual(self.post().status_code, 409)
        self.assertEqual(json.loads(self.repo.files["state/runtime-test.json"])["next_record_id"], 1)
        self.assertEqual(self.repo.commits, [])
        self.assertEqual(self.post().status_code, 201)
        self.assertEqual(self.post().json()["record_id"], "test-0002")
        self.assertEqual(json.loads(self.repo.files["state/runtime-test.json"])["next_record_id"], 3)
        self.assertEqual(len(self.repo.commits), 2)

    def test_photo_partitions_use_independent_counters_and_server_ids(self):
        self.login(modules=[MODULE_FOTO_PAPIERABZUEGE])
        expected = [("A", 7), ("B", 1), ("C", 1), ("A", 8), ("D", 1), ("E", 1), ("F", 1)]
        for index, (format_code, number) in enumerate(expected, start=4):
            with self.subTest(format=format_code, number=number):
                payload = self.full_photo_payload(sample_record("foto-000004", format_code, number))
                created = self.post(payload, module=MODULE_FOTO_PAPIERABZUEGE)
                self.assertEqual(created.status_code, 201, created.text)
                self.assertEqual(created.json()["record_id"], f"foto-{index:06d}")
                stored = parse_record_content(self.repo.files[f"data/fotos/foto-{index:06d}.md"])
                self.assertEqual(stored["signatur"]["anzeige"], f"9.4.2.{format_code}.{number}")
                self.assertEqual(stored["signatur"]["status"], "vergeben")
        state = json.loads(self.repo.files["state/foto-papierabzuege.json"])
        self.assertEqual(state["next_record_id"], 11)
        self.assertEqual(state["next_signature_number"], {"A": 9, "B": 2, "C": 2, "D": 2, "E": 2, "F": 2})

    def test_missing_or_bad_state_does_not_guess_counters(self):
        self.login()
        original = self.repo.files.pop("state/runtime-test.json")
        self.assertEqual(self.post().status_code, 422)
        self.repo.files["state/runtime-test.json"] = '{"next_record_id": 0}'
        self.assertEqual(self.post().status_code, 422)
        self.assertEqual(self.repo.commits, [])
        self.repo.files["state/runtime-test.json"] = original

    def test_create_collision_and_failed_validation_leave_state_unchanged(self):
        self.login()
        state = self.repo.files["state/runtime-test.json"]
        bad = valid_payload()
        bad["daten"]["name"] = None
        self.assertEqual(self.post(bad).status_code, 422)
        self.assertEqual(self.repo.files["state/runtime-test.json"], state)
        self.repo.files["data/test/test-0001.md"] = "occupied"
        self.assertEqual(self.post().status_code, 409)
        self.assertEqual(self.repo.files["state/runtime-test.json"], state)

    def test_client_cannot_choose_id_or_signature_and_update_does_not_allocate(self):
        self.login(modules=[MODULE_FOTO_PAPIERABZUEGE])
        payload = self.full_photo_payload(sample_record("foto-000004", "B", 1))
        for forbidden in ({"id": "foto-999999"}, {"signatur": {**payload["signatur"], "nummer": 999}}):
            attempt = deepcopy(payload)
            attempt.update(forbidden)
            self.assertIn(self.post(attempt, module=MODULE_FOTO_PAPIERABZUEGE).status_code, (403, 422))
        self.assertEqual(json.loads(self.repo.files["state/foto-papierabzuege.json"])["next_record_id"], 4)
        created = self.post(payload, module=MODULE_FOTO_PAPIERABZUEGE)
        self.assertEqual(created.status_code, 201, created.text)
        state = self.repo.files["state/foto-papierabzuege.json"]
        stored = parse_record_content(self.repo.files["data/fotos/foto-000004.md"])
        payload["erschliessung"]["beschriftung"] = "Geaendert"
        updated = self.put("foto-000004", payload, created.json()["meta"]["revision"], module=MODULE_FOTO_PAPIERABZUEGE)
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(self.repo.files["state/foto-papierabzuege.json"], state)
        after = parse_record_content(self.repo.files["data/fotos/foto-000004.md"])
        self.assertEqual(after["id"], stored["id"])
        self.assertEqual(after["signatur"], stored["signatur"])
        payload["signatur"]["format"] = "C"
        self.assertEqual(self.put("foto-000004", payload, updated.json()["meta"]["revision"], module=MODULE_FOTO_PAPIERABZUEGE).status_code, 422)
        self.assertEqual(self.repo.files["state/foto-papierabzuege.json"], state)

    def test_update_requires_complete_payload_and_matching_revision(self):
        self.login()
        created = self.post().json()
        original = parse_record_content(self.repo.files["data/test/test-0001.md"])
        payload = valid_payload()
        payload["daten"]["name"] = "Neu"
        payload["daten"]["place"]["name"] = "Linz"
        payload["daten"]["beteiligte"] = [{"name": "Erste"}, {"name": "Zweite", "rolle": "absender"}]
        response = self.put("test-0001", payload, created["meta"]["revision"])
        self.assertEqual(response.status_code, 200, response.text)
        updated = parse_record_content(self.repo.files["data/test/test-0001.md"])
        self.assertEqual(updated["daten"]["name"], "Neu")
        self.assertEqual(updated["daten"]["place"]["name"], "Linz")
        self.assertEqual(len(updated["daten"]["beteiligte"]), 2)
        self.assertEqual(updated["daten"]["beteiligte"][1]["rolle"], "absender")
        self.assertEqual(updated["technik"]["erstellt_am"], original["technik"]["erstellt_am"])
        self.assertEqual(updated["technik"]["erstellt_von"], "anna")
        self.assertEqual(updated["technik"]["geaendert_von"], "anna")
        self.assertTrue(updated["technik"]["geaendert_am"])
        self.assertNotIn("base_revision", updated)
        self.assertNotEqual(created["meta"]["revision"], response.json()["meta"]["revision"])

        before = deepcopy(self.repo.files)
        self.assertEqual(self.put("test-0001", payload, created["meta"]["revision"]).status_code, 409)
        self.assertEqual(self.put("test-0001", payload, None).status_code, 422)
        self.assertEqual(self.put("test-0001", {"daten": {"name": "Teil"}}, response.json()["meta"]["revision"]).status_code, 422)
        self.assertEqual(self.repo.files, before)

    def test_update_rejects_unknown_readonly_hidden_and_technical_values(self):
        self.login()
        created = self.post().json()
        revision = created["meta"]["revision"]
        cases = [
            ({"daten": {"unknown": "x"}}, 422),
            ({"daten": {"readonly": "x"}}, 403),
            ({"daten": {"secret": "x"}}, 403),
            ({"technik": {"geaendert_von": "client"}}, 403),
            ({"id": "client-id"}, 403),
        ]
        for forbidden, expected in cases:
            payload = valid_payload()
            payload["daten"].update(forbidden.get("daten", {}))
            payload.update({key: value for key, value in forbidden.items() if key != "daten"})
            with self.subTest(forbidden=forbidden):
                before = deepcopy(self.repo.files)
                self.assertEqual(self.put("test-0001", payload, revision).status_code, expected)
                self.assertEqual(self.repo.files, before)
        self.assertEqual(self.put("test-0001", {"daten": {"readonly": "x"}}, revision).status_code, 403)
        self.assertEqual(len(self.repo.commits), 1)

    def test_redaktion_and_admin_follow_module_rights_without_technical_override(self):
        self.login()
        created = self.post().json()
        self.login(username="rita", role="redaktion")
        payload = valid_payload()
        payload["daten"]["secret"] = "redaktionell"
        payload["daten"]["readonly"] = "bearbeitet"
        response = self.put("test-0001", payload, created["meta"]["revision"])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["record"]["daten"]["secret"], "redaktionell")

        self.login(username="admin", role="admin")
        payload["technik"] = {"erstellt_von": "admin"}
        before = deepcopy(self.repo.files)
        self.assertEqual(self.put("test-0001", payload, response.json()["meta"]["revision"]).status_code, 403)
        self.assertEqual(self.repo.files, before)

    def test_update_not_found_conflict_and_persistence_failure(self):
        self.login()
        self.assertEqual(self.put("test-9999", valid_payload(), "any").status_code, 404)
        created = self.post().json()
        before = deepcopy(self.repo.files)
        self.repo._conflict_failures = 1
        self.assertEqual(self.put("test-0001", valid_payload(), created["meta"]["revision"]).status_code, 409)
        self.assertEqual(self.repo.files, before)
        self.assertEqual(len(self.repo.commits), 1)

        failing = FailingRepository(self.repo.files)
        self.app.state.data_repository = failing
        self.assertEqual(self.put("test-0001", valid_payload(), failing.read_file("data/test/test-0001.md").revision).status_code, 500)
        self.assertEqual(failing.commits, [])
        self.assertEqual(failing.files, before)

    def test_update_preserves_readonly_and_hidden_values_and_rejects_schema_error(self):
        self.login()
        self.assertEqual(self.post().status_code, 201)
        path = "data/test/test-0001.md"
        stored = parse_record_content(self.repo.files[path])
        stored["daten"]["readonly"] = "gesperrt"
        stored["daten"]["secret"] = "verborgen"
        self.repo.files[path] = render_record_content(stored)
        revision = self.repo.read_file(path).revision
        payload = valid_payload()
        payload["daten"]["name"] = "Geaendert"
        response = self.put("test-0001", payload, revision)
        self.assertEqual(response.status_code, 200, response.text)
        updated = parse_record_content(self.repo.files[path])
        self.assertEqual(updated["daten"]["readonly"], "gesperrt")
        self.assertEqual(updated["daten"]["secret"], "verborgen")
        self.assertNotIn("secret", response.json()["record"]["daten"])

        before = deepcopy(self.repo.files)
        commits = len(self.repo.commits)
        payload["daten"]["date_range"] = {"from": {"year": "ungueltig"}}
        self.assertEqual(self.put("test-0001", payload, response.json()["meta"]["revision"]).status_code, 422)
        self.assertEqual(self.repo.files, before)
        self.assertEqual(len(self.repo.commits), commits)

    def test_update_preserves_unstructured_markdown_body(self):
        self.login()
        self.assertEqual(self.post().status_code, 201)
        path = "data/test/test-0001.md"
        self.repo.files[path] += "Zusaetzlicher Freitext.\n"
        revision = self.repo.read_file(path).revision
        response = self.put("test-0001", valid_payload(), revision)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(self.repo.files[path].endswith("Zusaetzlicher Freitext.\n"))

    def test_photo_module_create_update_and_permissions_stay_in_memory(self):
        self.login(modules=[MODULE_FOTO_PAPIERABZUEGE])
        example = sample_record("foto-000004", "A", 7)
        payload = self.full_photo_payload(example)
        created = self.post(payload, module=MODULE_FOTO_PAPIERABZUEGE)
        self.assertEqual(created.status_code, 201, created.text)
        self.assertNotIn("titel", created.json()["record"]["erschliessung"])
        path = "data/fotos/foto-000004.md"
        self.assertIn(path, self.repo.files)
        self.assertEqual(self.repo.commits[0]["files"], [path, "state/foto-papierabzuege.json"])

        payload["erschliessung"]["beschriftung"] = "Neue Beschriftung"
        payload["erschliessung"]["beschreibung"] = "Neue Beschreibung"
        payload["erschliessung"]["dargestellte_personen"] = [{"name": "A"}, {"name": "B", "hinweis": "links"}]
        payload["datierung"]["jahr"] = 1967
        updated = self.put("foto-000004", payload, created.json()["meta"]["revision"], module=MODULE_FOTO_PAPIERABZUEGE)
        self.assertEqual(updated.status_code, 200, updated.text)
        stored = parse_record_content(self.repo.files[path])
        self.assertEqual(stored["erschliessung"]["beschreibung"], "Neue Beschreibung")
        self.assertEqual(stored["erschliessung"]["dargestellte_personen"][1]["name"], "B")
        self.assertEqual(stored["datierung"]["jahr"], 1967)
        self.assertIsNone(stored["erschliessung"]["titel"])
        self.assertEqual(stored["technik"]["geaendert_von"], "anna")
        self.assertEqual(self.put("foto-000004", payload, created.json()["meta"]["revision"], module=MODULE_FOTO_PAPIERABZUEGE).status_code, 409)

        payload["erschliessung"]["titel"] = "unerlaubt"
        before = deepcopy(self.repo.files)
        self.assertEqual(self.put("foto-000004", payload, updated.json()["meta"]["revision"], module=MODULE_FOTO_PAPIERABZUEGE).status_code, 403)
        self.assertEqual(self.repo.files, before)

    def test_photo_existing_record_can_be_edited_by_redaktion_without_old_endpoint(self):
        self.login(username="rita", role="redaktion", modules=[MODULE_FOTO_PAPIERABZUEGE])
        example = sample_record("foto-000001", "A", 7)
        example["erschliessung"]["titel"] = "Alter Titel"
        path = "data/fotos/foto-000001.md"
        self.repo.files[path] = render_photo_markdown(example)
        payload = self.full_photo_payload(example, role="redaktion")
        payload["erschliessung"]["titel"] = "Neuer Titel"
        revision = self.repo.read_file(path).revision
        response = self.put("foto-000001", payload, revision, module=MODULE_FOTO_PAPIERABZUEGE)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["record"]["erschliessung"]["titel"], "Neuer Titel")
        self.assertEqual(parse_record_content(self.repo.files[path])["technik"]["erstellt_von"], "seed")


if __name__ == "__main__":
    unittest.main()
