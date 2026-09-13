import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml


TEMP_DIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(TEMP_DIR.name) / 'generic-records-test.sqlite3'}"
os.environ["COOKIE_SECURE"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from backend.auth.service import create_user  # noqa: E402
from backend.database import Base, SessionLocal, engine  # noqa: E402
from backend.github.repository import InMemoryGitRepository  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.models import ModuleAccess  # noqa: E402
from backend.permissions import MODULE_FOTO_PAPIERABZUEGE  # noqa: E402
from backend.records.photos import read_photo_record  # noqa: E402
from backend.records.photo_index import INDEX_PATH, build_photo_index, dump_photo_index  # noqa: E402
from scripts.foto_core import render_photo_markdown  # noqa: E402
from tests.test_record_runtime import valid_payload, write_runtime_module, write_runtime_schema  # noqa: E402
from tests.test_records_api import sample_record  # noqa: E402


def markdown_record(data: dict) -> str:
    return "---\n" + yaml.safe_dump(data, allow_unicode=True, sort_keys=False) + "---\n"


class GenericRecordsApiTest(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.app = create_app()
        self.repository = InMemoryGitRepository()
        self.app.state.data_repository = self.repository
        self.client = TestClient(self.app)

    def create_user(self, username="anna", role="ehrenamtlich", modules=None):
        if modules is None:
            modules = [MODULE_FOTO_PAPIERABZUEGE]
        create_modules = modules if set(modules).issubset({MODULE_FOTO_PAPIERABZUEGE}) else [MODULE_FOTO_PAPIERABZUEGE]
        with SessionLocal() as db:
            user = create_user(
                db,
                username=username,
                display_name=username.title(),
                email=f"{username}@example.test",
                role=role,
                ui_profile="redaktion" if role != "ehrenamtlich" else "ehrenamt-standard",
                modules=create_modules,
                password="SehrGeheim123",
            )
            if modules != create_modules:
                user.module_access.clear()
                user.module_access.extend(ModuleAccess(module_key=module) for module in modules)
            db.commit()
            return user.id

    def login(self, username="anna"):
        response = self.client.post("/api/auth/login", json={"login": username, "password": "SehrGeheim123"})
        self.assertEqual(response.status_code, 200)

    def authed(self, username="anna", role="ehrenamtlich", modules=None):
        self.create_user(username=username, role=role, modules=modules)
        self.login(username)

    def seed_photo(self):
        record = sample_record("foto-000001", "A", 7)
        record["erschliessung"]["titel"] = "Redaktionstitel"
        record["erschliessung"]["beschriftung"] = "Beschriftung"
        record["erschliessung"]["dargestellte_personen"] = [{"name": "Person A", "hinweis": "links"}]
        record["datierung"] = {"jahr": 1966, "monat": 5, "tag": None, "anmerkung": "vermutet"}
        self.repository.files["data/fotos/foto-000001.md"] = render_photo_markdown(record)
        self.repository.files[INDEX_PATH] = dump_photo_index(build_photo_index([record]))
        return record

    def test_generic_get_photo_matches_existing_read_logic_and_filters_role(self):
        record = self.seed_photo()
        self.authed()
        existing = read_photo_record(self.repository, "foto-000001")

        response = self.client.get("/api/modules/foto_papierabzuege/records/foto-000001")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["module"], MODULE_FOTO_PAPIERABZUEGE)
        self.assertEqual(data["record_id"], "foto-000001")
        self.assertEqual(data["record"]["id"], existing.data["id"])
        self.assertEqual(data["record"]["signatur"]["anzeige"], record["signatur"]["anzeige"])
        self.assertEqual(data["record"]["erschliessung"]["beschriftung"], "Beschriftung")
        self.assertEqual(data["record"]["erschliessung"]["dargestellte_personen"][0]["name"], "Person A")
        self.assertEqual(data["record"]["datierung"]["jahr"], 1966)
        self.assertNotIn("titel", data["record"]["erschliessung"])
        self.assertIn("revision", data["meta"])

    def test_redaktion_sees_configured_redaktion_field(self):
        self.seed_photo()
        self.authed(username="rita", role="redaktion")
        response = self.client.get("/api/modules/foto_papierabzuege/records/foto-000001")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["record"]["erschliessung"]["titel"], "Redaktionstitel")

    def test_generic_photo_list_uses_configured_columns_and_revision_meta(self):
        self.seed_photo()
        self.authed()
        response = self.client.get("/api/modules/foto_papierabzuege/records")
        self.assertEqual(response.status_code, 200)
        records = response.json()["records"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["record_id"], "foto-000001")
        self.assertEqual(records[0]["values"]["signatur.anzeige"], "9.4.2.A.7")
        self.assertEqual(records[0]["values"]["erschliessung.beschriftung"], "Beschriftung")
        self.assertIn("revision", records[0]["meta"])

    def test_generic_record_errors(self):
        self.authed()
        self.assertEqual(self.client.get("/api/modules/unbekannt/records").status_code, 404)
        self.assertEqual(self.client.get("/api/modules/foto_papierabzuege/records/foto-999999").status_code, 404)

    def test_missing_module_access_is_forbidden(self):
        self.create_user(modules=[])
        self.login()
        response = self.client.get("/api/modules/foto_papierabzuege/records")
        self.assertEqual(response.status_code, 403)

    def test_generic_writes_remain_disabled_without_test_configuration(self):
        self.authed()
        me = self.client.get("/api/auth/me").json()
        csrf = self.client.cookies.get(me["csrf_cookie_name"])
        response = self.client.post(
            "/api/modules/foto_papierabzuege/records",
            json={"record": {}},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.repository.commits, [])

    def test_same_generic_route_reads_second_module_without_photo_logic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            schema_path = write_runtime_schema(root)
            module = __import__("backend.modules", fromlist=["load_module"]).load_module(write_runtime_module(root, schema_path))
            record = {
                "id": "test-0001",
                "datensatz_typ": "test",
                **valid_payload(),
                "technik": {"erstellt_am": None, "erstellt_von": None, "geaendert_am": None, "geaendert_von": None},
            }
            record["daten"]["secret"] = "redaktionell"
            self.repository.files["data/test/test-0001.md"] = markdown_record(record)
            self.authed(modules=["runtime_test"])
            with patch("backend.routes.modules.get_module", return_value=module):
                detail = self.client.get("/api/modules/runtime_test/records/test-0001")
                listing = self.client.get("/api/modules/runtime_test/records")

        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["record"]["daten"]["name"], "Test")
        self.assertEqual(len(detail.json()["record"]["daten"]["beteiligte"]), 2)
        self.assertEqual(detail.json()["record"]["daten"]["date_range"]["from"]["year"], 1900)
        self.assertNotIn("secret", detail.json()["record"]["daten"])
        self.assertEqual(listing.status_code, 200)
        values = listing.json()["records"][0]["values"]
        self.assertEqual(values["daten.name"], "Test")
        self.assertNotIn("daten.secret", values)


if __name__ == "__main__":
    unittest.main()
