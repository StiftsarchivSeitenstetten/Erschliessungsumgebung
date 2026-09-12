import os
import json
from pathlib import Path
import tempfile
import unittest


TEMP_DIR = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = f"sqlite:///{Path(TEMP_DIR.name) / 'records-test.sqlite3'}"
os.environ["COOKIE_SECURE"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from backend.auth.service import create_user  # noqa: E402
from backend.database import Base, SessionLocal, engine  # noqa: E402
from backend.github.repository import InMemoryGitRepository  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.permissions import MODULE_FOTO_PAPIERABZUEGE  # noqa: E402
from backend.records.photo_index import INDEX_PATH, build_photo_index, dump_photo_index  # noqa: E402
from scripts.foto_core import build_signature, render_photo_markdown  # noqa: E402


def payload(format_code: str = "A", beschriftung: str = "Testdatensatz") -> dict:
    return {
        "format": format_code,
        "erschliessung": {
            "titel": None,
            "beschriftung": beschriftung,
            "beschreibung": None,
            "dargestellte_personen": [{"name": "Kurzwernhart, Albert", "hinweis": "vermutlich"}],
            "herkunft": "Fotofaszikel Otto Raus",
            "sammler": None,
            "fotograf": None,
            "rechteinhaber": None,
            "orte": [],
            "schlagworte": [],
            "altsignaturen": [],
            "interne_bemerkung": None,
        },
        "korrespondenzstueck": False,
        "datierung": {"jahr": 1966, "monat": None, "tag": None, "anmerkung": "vermutet"},
    }


def sample_record(record_id: str, format_code: str, nummer: int, redaktion: str = "ehrenamtlich") -> dict:
    data = payload(format_code, f"Bestehend {record_id}")
    return {
        "schema_version": 1,
        "id": record_id,
        "datensatz_typ": "foto",
        "modul": "papierabzuege_9_4_2",
        "signatur": build_signature(format_code, nummer),
        "erschliessung": data["erschliessung"],
        "korrespondenzstueck": False,
        "datierung": data["datierung"],
        "redaktion": {"stufe": redaktion},
        "bearbeitung": {"status": "in_bearbeitung"},
        "publikation": {"status": "intern"},
        "technik": {
            "quelle": "webapp",
            "erstellt_am": "2026-09-11T00:00:00Z",
            "erstellt_von": "seed",
            "geaendert_am": None,
            "geaendert_von": None,
        },
    }


class RecordsApiTest(unittest.TestCase):
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
        with SessionLocal() as db:
            user = create_user(
                db,
                username=username,
                display_name=username.title(),
                email=f"{username}@example.test",
                role=role,
                ui_profile="redaktion" if role != "ehrenamtlich" else "ehrenamt-standard",
                modules=modules,
                password="SehrGeheim123",
            )
            db.commit()
            return user.id

    def login(self, username="anna"):
        response = self.client.post("/api/auth/login", json={"login": username, "password": "SehrGeheim123"})
        self.assertEqual(response.status_code, 200)
        return response

    def csrf(self):
        me = self.client.get("/api/auth/me")
        return self.client.cookies.get(me.json()["csrf_cookie_name"])

    def authed(self, username="anna", role="ehrenamtlich", modules=None):
        self.create_user(username=username, role=role, modules=modules)
        self.login(username)

    def post_photo(self, data=None):
        return self.client.post(
            "/api/records/photos",
            json=data or payload(),
            headers={"X-CSRF-Token": self.csrf()},
        )

    def test_create_new_record_assigns_backend_id_signature_and_provenance(self):
        self.authed()
        response = self.post_photo()
        self.assertEqual(response.status_code, 201)
        record = response.json()["record"]
        self.assertEqual(record["id"], "foto-000001")
        self.assertEqual(record["signatur"]["anzeige"], "9.4.2.A.1")
        self.assertEqual(record["signatur"]["status"], "vergeben")
        self.assertEqual(record["technik"]["quelle"], "webapp")
        self.assertEqual(record["technik"]["erstellt_von"], "anna")
        self.assertEqual(record["technik"]["geaendert_von"], "anna")
        self.assertIsNotNone(record["technik"]["erstellt_am"])
        self.assertEqual(record["technik"]["geaendert_am"], record["technik"]["erstellt_am"])
        self.assertIn("data/fotos/foto-000001.md", self.repository.files)
        self.assertIn("state/foto-papierabzuege.json", self.repository.files)
        self.assertIn("indexes/fotos.json", self.repository.files)
        state = json.loads(self.repository.files["state/foto-papierabzuege.json"])
        self.assertEqual(state["next_record_id"], 2)
        self.assertEqual(state["next_signature_number"]["A"], 2)
        index = json.loads(self.repository.files["indexes/fotos.json"])
        self.assertEqual(index["records"], [{
            "id": "foto-000001",
            "signatur": "9.4.2.A.1",
            "format": "A",
            "nummer": 1,
            "zusatz": None,
        }])
        self.assertEqual(self.repository.commits[-1]["files"], [
            "data/fotos/foto-000001.md",
            "indexes/fotos.json",
            "state/foto-papierabzuege.json",
        ])

    def test_create_record_reads_import_style_state(self):
        self.repository.files["state/foto-papierabzuege.json"] = json.dumps({
            "next_record_id": 10332,
            "next_signature_number": {"A": 8610, "B": 1046, "C": 579, "D": 81, "E": 36, "F": 1},
        })
        self.authed()
        response = self.post_photo(payload("A"))
        self.assertEqual(response.status_code, 201)
        record = response.json()["record"]
        self.assertEqual(record["id"], "foto-010332")
        self.assertEqual(record["signatur"]["anzeige"], "9.4.2.A.8610")
        state = json.loads(self.repository.files["state/foto-papierabzuege.json"])
        self.assertEqual(state["next_record_id"], 10333)
        self.assertEqual(state["next_signature_number"]["A"], 8611)

    def test_separate_number_ranges_for_a_b_c(self):
        self.authed()
        a = self.post_photo(payload("A")).json()["record"]
        b = self.post_photo(payload("B")).json()["record"]
        c = self.post_photo(payload("C")).json()["record"]
        a2 = self.post_photo(payload("A")).json()["record"]
        self.assertEqual(a["signatur"]["anzeige"], "9.4.2.A.1")
        self.assertEqual(b["signatur"]["anzeige"], "9.4.2.B.1")
        self.assertEqual(c["signatur"]["anzeige"], "9.4.2.C.1")
        self.assertEqual(a2["signatur"]["anzeige"], "9.4.2.A.2")
        self.assertEqual(len({a["id"], b["id"], c["id"], a2["id"]}), 4)

    def test_two_create_attempts_never_share_id_or_signature(self):
        self.authed()
        first = self.post_photo(payload("A")).json()["record"]
        second = self.post_photo(payload("A")).json()["record"]
        self.assertNotEqual(first["id"], second["id"])
        self.assertNotEqual(first["signatur"]["anzeige"], second["signatur"]["anzeige"])

    def test_retry_after_ref_conflict(self):
        self.repository._conflict_failures = 1
        self.authed()
        response = self.post_photo(payload("A"))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["record"]["signatur"]["anzeige"], "9.4.2.A.1")
        self.assertEqual(len(self.repository.commits), 1)

    def seed_existing(self, record_id="foto-000001", format_code="A", nummer=7, redaktion="ehrenamtlich"):
        record = sample_record(record_id, format_code, nummer, redaktion)
        self.repository.files[f"data/fotos/{record_id}.md"] = render_photo_markdown(record)
        self.repository.files[INDEX_PATH] = dump_photo_index(build_photo_index([record]))
        return record

    def test_read_record_and_list(self):
        self.seed_existing()
        self.authed()
        listing = self.client.get("/api/records/photos")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["records"][0]["id"], "foto-000001")
        self.assertEqual(self.repository.list_directory_calls, [])
        detail = self.client.get("/api/records/photos/foto-000001")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["record"]["signatur"]["anzeige"], "9.4.2.A.7")

    def test_read_record_by_signature_uses_index(self):
        self.seed_existing()
        self.authed()
        response = self.client.get("/api/records/photos/signatures/9.4.2.A.7")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["record"]["id"], "foto-000001")
        self.assertNotIn("data/fotos", self.repository.list_directory_calls)

    def test_ref_conflict_does_not_partially_update_index(self):
        self.repository._conflict_failures = 5
        self.authed()
        response = self.post_photo(payload("A"))
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("data/fotos/foto-000001.md", self.repository.files)
        self.assertNotIn(INDEX_PATH, self.repository.files)
        self.assertEqual(len(self.repository.commits), 0)

    def test_ehrenamt_updates_ehrenamt_record(self):
        self.seed_existing()
        self.authed()
        loaded = self.client.get("/api/records/photos/foto-000001").json()
        data = payload("A", "Geändert")
        data["base_revision"] = loaded["base_revision"]
        response = self.client.put(
            "/api/records/photos/foto-000001",
            json=data,
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(response.status_code, 200)
        record = response.json()["record"]
        self.assertEqual(record["erschliessung"]["beschriftung"], "Geändert")
        self.assertEqual(record["technik"]["erstellt_von"], "seed")
        self.assertEqual(record["technik"]["erstellt_am"], "2026-09-11T00:00:00Z")
        self.assertEqual(record["technik"]["geaendert_von"], "anna")
        self.assertIsNotNone(record["technik"]["geaendert_am"])

    def test_update_legacy_record_without_created_provenance_does_not_invent_it(self):
        record = self.seed_existing()
        record["technik"] = {"quelle": "migration_excel", "erstellt_am": None, "erstellt_von": None}
        self.repository.files["data/fotos/foto-000001.md"] = render_photo_markdown(record)
        self.authed()
        loaded = self.client.get("/api/records/photos/foto-000001").json()
        data = payload("A", "Legacy geändert")
        data["base_revision"] = loaded["base_revision"]
        response = self.client.put(
            "/api/records/photos/foto-000001",
            json=data,
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(response.status_code, 200)
        technik = response.json()["record"]["technik"]
        self.assertEqual(technik["quelle"], "migration_excel")
        self.assertIsNone(technik["erstellt_am"])
        self.assertIsNone(technik["erstellt_von"])
        self.assertEqual(technik["geaendert_von"], "anna")
        self.assertIsNotNone(technik["geaendert_am"])

    def test_ehrenamt_reads_but_does_not_update_redaktionell_record(self):
        self.seed_existing(redaktion="redaktionell")
        self.authed()
        loaded = self.client.get("/api/records/photos/foto-000001")
        self.assertEqual(loaded.status_code, 200)
        data = payload("A", "Nicht erlaubt")
        data["base_revision"] = loaded.json()["base_revision"]
        response = self.client.put(
            "/api/records/photos/foto-000001",
            json=data,
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(response.status_code, 403)

    def test_redaktion_updates_redaktionell_record(self):
        self.seed_existing(redaktion="redaktionell")
        self.authed(username="rita", role="redaktion")
        loaded = self.client.get("/api/records/photos/foto-000001").json()
        data = payload("A", "Redaktion ändert")
        data["base_revision"] = loaded["base_revision"]
        response = self.client.put(
            "/api/records/photos/foto-000001",
            json=data,
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(response.status_code, 200)

    def test_stale_base_revision_returns_409(self):
        self.seed_existing()
        self.authed()
        data = payload("A", "Alt")
        data["base_revision"] = "veraltet"
        response = self.client.put(
            "/api/records/photos/foto-000001",
            json=data,
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("inzwischen", response.json()["detail"])

    def test_schema_error_does_not_commit(self):
        self.authed()
        bad = payload("A")
        bad["datierung"] = {"jahr": 1966, "monat": 13, "tag": None}
        response = self.post_photo(bad)
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.repository.commits, [])

    def test_missing_module_access_cannot_read_or_write(self):
        self.authed(modules=[])
        self.assertEqual(self.client.get("/api/records/photos").status_code, 403)
        self.assertEqual(self.post_photo().status_code, 403)
        self.assertEqual(self.repository.commits, [])

    def test_unauthenticated_cannot_read_or_write(self):
        self.assertEqual(self.client.get("/api/records/photos").status_code, 401)
        response = self.client.post("/api/records/photos", json=payload(), headers={"X-CSRF-Token": "x"})
        self.assertEqual(response.status_code, 401)

    def test_csrf_error_blocks_write(self):
        self.authed()
        response = self.client.post("/api/records/photos", json=payload())
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.repository.commits, [])


if __name__ == "__main__":
    unittest.main()
