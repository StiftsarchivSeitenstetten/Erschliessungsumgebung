from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.auth.service import create_user
from backend.database import Base, SessionLocal, engine
from backend.github.repository import InMemoryGitRepository
from backend.main import create_app
from backend.modules import load_module
from backend.records.runtime import RecordRuntime
from tests.test_record_runtime import valid_payload, write_runtime_module, write_runtime_schema


ROOT = Path(__file__).resolve().parents[1]
PATH = "vocabularies/dokumenttypen.yaml"


class VocabularyWriteApiTest(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.module = load_module(write_runtime_module(root, write_runtime_schema(root)))
        self.module_patch = patch("backend.routes.modules.list_modules", return_value=(self.module,))
        self.module_patch.start()
        self.repository = InMemoryGitRepository({
            PATH: (ROOT / PATH).read_text(encoding="utf-8"),
        })
        self.app = create_app()
        self.app.state.data_repository = self.repository
        self.client = TestClient(self.app)

    def tearDown(self):
        self.module_patch.stop()
        self.tmp.cleanup()

    def login(self, role="redaktion", username="rita"):
        with SessionLocal() as db:
            create_user(
                db, username=username, display_name=username.title(), email=f"{username}@example.test",
                role=role, ui_profile="redaktion" if role != "ehrenamtlich" else "ehrenamt-standard",
                modules=[], password="SehrGeheim123",
            )
            db.commit()
        response = self.client.post("/api/auth/login", json={"login": username, "password": "SehrGeheim123"})
        self.assertEqual(response.status_code, 200)

    def csrf(self):
        me = self.client.get("/api/auth/me").json()
        return {"X-CSRF-Token": self.client.cookies.get(me["csrf_cookie_name"])}

    def test_read_add_rename_deactivate_end_to_end(self):
        self.login()
        loaded = self.client.get("/api/vocabularies/dokumenttypen")
        self.assertEqual(loaded.status_code, 200, loaded.text)
        revision = loaded.json()["meta"]["revision"]

        added = self.client.post(
            "/api/vocabularies/dokumenttypen/terms",
            json={"base_revision": revision, "term": {"id": "tagebuch", "label": "Tagebuch"}},
            headers=self.csrf(),
        )
        self.assertEqual(added.status_code, 201, added.text)
        revision = added.json()["meta"]["revision"]
        self.assertNotEqual(revision, self.repository.get_branch_head())
        self.assertEqual(added.json()["vocabulary"]["terms"][-1]["id"], "tagebuch")
        record = valid_payload()
        record["daten"]["term"] = {"id": "tagebuch", "vocabulary_id": "dokumenttypen"}
        RecordRuntime(self.module, self.repository).validate_vocabulary_references(record)

        renamed = self.client.patch(
            "/api/vocabularies/dokumenttypen/terms/tagebuch",
            json={"base_revision": revision, "label": "Journal"}, headers=self.csrf(),
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)
        revision = renamed.json()["meta"]["revision"]
        term = next(term for term in renamed.json()["vocabulary"]["terms"] if term["id"] == "tagebuch")
        self.assertEqual(term["label"], "Journal")

        deactivated = self.client.patch(
            "/api/vocabularies/dokumenttypen/terms/tagebuch",
            json={"base_revision": revision, "active": False}, headers=self.csrf(),
        )
        self.assertEqual(deactivated.status_code, 200, deactivated.text)
        read_back = self.client.get("/api/vocabularies/dokumenttypen").json()
        term = next(term for term in read_back["terms"] if term["id"] == "tagebuch")
        self.assertEqual(term, {
            "id": "tagebuch", "label": "Journal", "active": False,
            "description": None, "aliases": [], "sort_order": None,
        })

    def test_auth_csrf_permissions_and_errors(self):
        self.assertEqual(self.client.post("/api/vocabularies/dokumenttypen/terms", json={}).status_code, 401)
        self.login(role="ehrenamtlich", username="anna")
        loaded = self.client.get("/api/vocabularies/dokumenttypen")
        self.assertEqual(loaded.status_code, 200)
        revision = loaded.json()["meta"]["revision"]
        body = {"base_revision": revision, "term": {"id": "neu", "label": "Neu"}}
        self.assertEqual(self.client.post("/api/vocabularies/dokumenttypen/terms", json=body).status_code, 403)
        self.assertEqual(self.client.post(
            "/api/vocabularies/dokumenttypen/terms", json=body, headers=self.csrf(),
        ).status_code, 403)
        for payload in (
            {"base_revision": revision, "label": "Neu"},
            {"base_revision": revision, "active": False},
        ):
            response = self.client.patch(
                "/api/vocabularies/dokumenttypen/terms/brief", json=payload, headers=self.csrf(),
            )
            self.assertEqual(response.status_code, 403)

    def test_conflict_not_found_and_invalid_payloads(self):
        self.login()
        revision = self.client.get("/api/vocabularies/dokumenttypen").json()["meta"]["revision"]
        first = self.client.patch(
            "/api/vocabularies/dokumenttypen/terms/brief",
            json={"base_revision": revision, "label": "Schreiben"}, headers=self.csrf(),
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.client.patch(
            "/api/vocabularies/dokumenttypen/terms/brief",
            json={"base_revision": revision, "active": False}, headers=self.csrf(),
        ).status_code, 409)
        current = first.json()["meta"]["revision"]
        self.assertEqual(self.client.patch(
            "/api/vocabularies/dokumenttypen/terms/fehlt",
            json={"base_revision": current, "label": "Neu"}, headers=self.csrf(),
        ).status_code, 404)
        self.assertEqual(self.client.patch(
            "/api/vocabularies/dokumenttypen/terms/brief",
            json={"base_revision": current, "label": "   "}, headers=self.csrf(),
        ).status_code, 422)
        self.assertEqual(self.client.post(
            "/api/vocabularies/dokumenttypen/terms",
            json={"base_revision": current, "term": {"id": "brief", "label": "Doppelt"}}, headers=self.csrf(),
        ).status_code, 409)
        self.assertEqual(self.client.post(
            "/api/vocabularies/dokumenttypen/terms",
            json={"base_revision": current, "term": {"id": "neu", "label": "Neu", "unknown": True}}, headers=self.csrf(),
        ).status_code, 422)
        self.assertEqual(self.client.patch(
            "/api/vocabularies/dokumenttypen/terms/brief",
            json={"base_revision": current, "active": True}, headers=self.csrf(),
        ).status_code, 422)
        self.assertEqual(self.client.get("/api/vocabularies/unbekannt").status_code, 404)
        self.assertEqual(len(self.repository.commits), 1)

    def test_write_does_not_create_missing_repository_vocabulary(self):
        self.repository.files.clear()
        self.login()
        response = self.client.post(
            "/api/vocabularies/dokumenttypen/terms",
            json={"base_revision": "local-revision", "term": {"id": "neu", "label": "Neu"}},
            headers=self.csrf(),
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.repository.commits, [])


if __name__ == "__main__":
    unittest.main()
