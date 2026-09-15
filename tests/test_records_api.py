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
from backend.records.photos import STATE_PATH  # noqa: E402
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

    def reserve_photo(self, operation_id, partition="A"):
        return self.client.post(
            "/api/records/photos/reservations",
            json={"operation_id": operation_id, "partition": partition},
            headers={"X-CSRF-Token": self.csrf()},
        )

    def test_reservation_is_persistent_atomic_and_idempotent(self):
        self.repository.files[STATE_PATH] = json.dumps({
            "next_record_id": 10334,
            "next_signature_number": {"A": 8610, "B": 1047, "C": 579, "D": 81, "E": 36, "F": 1},
        })
        self.authed()
        operation_id = "11111111-1111-4111-8111-111111111111"

        first = self.reserve_photo(operation_id, "B")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.json()["operation_id"], operation_id)
        self.assertEqual(first.json()["record_id"], "foto-010334")
        self.assertEqual(first.json()["signature"], "9.4.2.B.1047")
        self.assertEqual(first.json()["signature_data"]["format"], "B")
        self.assertEqual(first.json()["signature_data"]["nummer"], 1047)
        self.assertEqual(first.json()["signature_data"]["anzeige"], "9.4.2.B.1047")
        self.assertEqual(first.json()["signature_data"]["status"], "vergeben")
        self.assertEqual(first.json()["partition"], "B")
        self.assertIsNotNone(first.json()["reserved_at"])
        persisted = json.loads(self.repository.files[STATE_PATH])
        self.assertEqual(persisted["next_record_id"], 10335)
        self.assertEqual(persisted["next_signature_number"]["B"], 1048)
        self.assertEqual(persisted["next_signature_number"]["A"], 8610)
        persisted_reservation = persisted["reservations"][operation_id]
        self.assertEqual(persisted_reservation["operation_id"], operation_id)
        self.assertEqual(persisted_reservation["record_id"], "foto-010334")
        self.assertEqual(persisted_reservation["signature"], "9.4.2.B.1047")
        self.assertEqual(persisted_reservation["partition"], "B")
        self.assertEqual(persisted_reservation["reserved_at"], first.json()["reserved_at"])
        self.assertEqual(self.repository.commits[-1]["files"], [STATE_PATH])

        retry = self.reserve_photo(operation_id, "B")
        self.assertEqual(retry.json(), first.json())
        self.assertEqual(len(self.repository.commits), 1)
        self.assertEqual(json.loads(self.repository.files[STATE_PATH]), persisted)

    def test_reservation_survives_new_repository_instance(self):
        self.authed()
        operation_id = "22222222-2222-4222-8222-222222222222"
        first = self.reserve_photo(operation_id, "C")
        persisted_files = dict(self.repository.files)

        restarted_repository = InMemoryGitRepository(files=persisted_files)
        self.app.state.data_repository = restarted_repository
        retry = self.reserve_photo(operation_id, "C")

        self.assertEqual(retry.json(), first.json())
        self.assertEqual(restarted_repository.commits, [])

    def test_new_operation_consumes_next_identity_and_abandoned_gap_remains(self):
        self.authed()
        first = self.reserve_photo("33333333-3333-4333-8333-333333333333", "D").json()
        second = self.reserve_photo("44444444-4444-4444-8444-444444444444", "D").json()
        self.assertEqual(first["record_id"], "foto-000001")
        self.assertEqual(first["signature"], "9.4.2.D.1")
        self.assertEqual(second["record_id"], "foto-000002")
        self.assertEqual(second["signature"], "9.4.2.D.2")
        self.assertNotIn("data/fotos/foto-000001.md", self.repository.files)

    def test_all_signature_partitions_advance_independently(self):
        self.authed()
        for index, partition in enumerate("ABCDEF", start=1):
            operation_id = f"00000000-0000-4000-8000-{index:012d}"
            reservation = self.reserve_photo(operation_id, partition)
            self.assertEqual(reservation.status_code, 201)
            self.assertEqual(reservation.json()["signature"], f"9.4.2.{partition}.1")
        persisted = json.loads(self.repository.files[STATE_PATH])
        self.assertEqual(persisted["next_record_id"], 7)
        self.assertEqual(persisted["next_signature_number"], {partition: 2 for partition in "ABCDEF"})

    def test_failed_reservation_does_not_partially_advance_state(self):
        self.repository._conflict_failures = 5
        self.authed()
        operation_id = "55555555-5555-4555-8555-555555555555"
        failed = self.reserve_photo(operation_id, "E")
        self.assertEqual(failed.status_code, 409)
        self.assertNotIn(STATE_PATH, self.repository.files)
        self.assertEqual(self.repository.commits, [])

        retry = self.reserve_photo(operation_id, "E")
        self.assertEqual(retry.status_code, 201)
        self.assertEqual(retry.json()["record_id"], "foto-000001")
        self.assertEqual(retry.json()["signature"], "9.4.2.E.1")

    def test_same_operation_cannot_change_partition(self):
        self.authed()
        operation_id = "66666666-6666-4666-8666-666666666666"
        self.assertEqual(self.reserve_photo(operation_id, "A").status_code, 201)
        conflict = self.reserve_photo(operation_id, "B")
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(len(self.repository.commits), 1)

    def test_reserved_create_reuses_identity_without_advancing_state_again(self):
        self.authed()
        operation_id = "77777777-7777-4777-8777-777777777777"
        reservation = self.reserve_photo(operation_id, "B").json()
        state_after_reservation = self.repository.files[STATE_PATH]
        data = payload("B")
        data.update({
            "operation_id": operation_id,
            "record_id": reservation["record_id"],
            "signature": reservation["signature"],
        })

        created = self.post_photo(data)
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["record"]["id"], reservation["record_id"])
        self.assertEqual(created.json()["record"]["signatur"]["anzeige"], reservation["signature"])
        self.assertEqual(self.repository.files[STATE_PATH], state_after_reservation)
        self.assertEqual(self.repository.commits[-1]["files"], [
            f"data/fotos/{reservation['record_id']}.md",
            "indexes/fotos.json",
        ])

        commits_after_create = list(self.repository.commits)
        repeated = self.post_photo(data)
        self.assertEqual(repeated.status_code, 201)
        self.assertEqual(repeated.json(), created.json())
        self.assertEqual(self.repository.commits, commits_after_create)
        self.assertEqual(self.repository.files[STATE_PATH], state_after_reservation)

    def test_reserved_identity_requires_matching_operation(self):
        self.authed()
        invalid = payload("A")
        invalid.update({"record_id": "foto-000001", "signature": "9.4.2.A.1"})
        response = self.post_photo(invalid)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.repository.commits, [])

    def test_reservation_requires_auth_csrf_uuid_and_valid_partition(self):
        operation_id = "88888888-8888-4888-8888-888888888888"
        unauthenticated = self.client.post(
            "/api/records/photos/reservations",
            json={"operation_id": operation_id, "partition": "A"},
            headers={"X-CSRF-Token": "x"},
        )
        self.assertEqual(unauthenticated.status_code, 401)

        self.authed()
        self.assertEqual(
            self.client.post(
                "/api/records/photos/reservations",
                json={"operation_id": operation_id, "partition": "A"},
            ).status_code,
            403,
        )
        self.assertEqual(self.reserve_photo("not-a-uuid", "A").status_code, 422)
        self.assertEqual(self.reserve_photo(operation_id, "Z").status_code, 422)
        extra_record_data = self.client.post(
            "/api/records/photos/reservations",
            json={"operation_id": operation_id, "partition": "A", "erschliessung": {}},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(extra_record_data.status_code, 422)
        self.assertEqual(self.repository.commits, [])

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

    def test_returned_revision_allows_immediate_followup_update(self):
        self.seed_existing()
        self.authed()
        loaded = self.client.get("/api/records/photos/foto-000001").json()

        first_payload = payload("A", "Erste Änderung")
        first_payload["base_revision"] = loaded["base_revision"]
        first = self.client.put(
            "/api/records/photos/foto-000001",
            json=first_payload,
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(first.status_code, 200)

        second_payload = payload("A", "Zweite Änderung")
        second_payload["base_revision"] = first.json()["base_revision"]
        second = self.client.put(
            "/api/records/photos/foto-000001",
            json=second_payload,
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["record"]["erschliessung"]["beschriftung"], "Zweite Änderung")

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
