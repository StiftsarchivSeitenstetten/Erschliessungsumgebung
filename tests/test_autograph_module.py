"""Acceptance tests for the declarative Autographs 9.6 module."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


TEMP_DIR = tempfile.TemporaryDirectory()
os.environ.setdefault("DATABASE_URL", f"sqlite:///{Path(TEMP_DIR.name) / 'autograph-test.sqlite3'}")
os.environ["COOKIE_SECURE"] = "false"

from fastapi.testclient import TestClient

from backend.auth.service import create_user
from backend.database import Base, SessionLocal, engine
from backend.github.repository import InMemoryGitRepository
from backend.main import create_app
from backend.modules import get_module, list_modules
from backend.permissions import MODULE_AUTOGRAPHEN_9_6, MODULE_FOTO_PAPIERABZUEGE
from backend.records.generic_read import parse_record_content
from backend.records.generic_write import create_generic_record, update_generic_record
from backend.records.module_index import dump_index, make_index, query_index, read_module_index
from backend.records.runtime import RecordPermissionError, RecordRuntime, RecordValidationError


ROOT = Path(__file__).resolve().parents[1]
ROLES = ["ehrenamtlich", "redaktion", "admin"]


def sample_payload(*, internal=True, ranged=False):
    payload = {
        "erschliessung": {
            "dokumenttyp": {"id": "brief", "vocabulary_id": "autographen_dokumenttypen"},
            "erhaltungsform": {"id": "original", "vocabulary_id": "autographen_erhaltungsformen"},
            "beteiligte": [
                {
                    "agent": {"type": "person", "name": "Max Mustermann"},
                    "rolle": {"id": "absender", "vocabulary_id": "autographen_beteiligtenrollen"},
                    "notiz": "Absender laut Unterschrift",
                },
                {
                    "agent": {"type": "organization", "name": "Stift Seitenstetten"},
                    "rolle": {"id": "empfaenger", "vocabulary_id": "autographen_beteiligtenrollen"},
                    "notiz": None,
                },
            ],
            "ort": {"name": "Wien"},
            "regest": "Brief von Max Mustermann an das Stift.",
            "bemerkungen": None,
            "altsignatur": "Autogr. 42",
        },
        "datierung": {"from": {"year": 1875, "month": 4, "day": 12}},
    }
    if ranged:
        payload["datierung"]["to"] = {"year": 1876}
        payload["datierung"]["hinweis"] = "Datierung erschlossen"
    if internal:
        payload["erschliessung"]["interne_bemerkung"] = "Nur intern."
    return payload


def repository_for(module):
    files = {
        module.storage["state"]["path"]: json.dumps({
            "next_record_id": 1,
            "next_signature_number": {"A": 1},
        }),
        module.storage["index"]["path"]: dump_index(make_index(module, [])),
    }
    for reference in module.vocabularies.values():
        files[reference["repository_path"]] = Path(reference["path"]).read_text(encoding="utf-8")
    return InMemoryGitRepository(files)


class AutographModuleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        list_modules.cache_clear()
        cls.module = get_module(MODULE_AUTOGRAPHEN_9_6)

    def setUp(self):
        self.repository = repository_for(self.module)
        self.runtime = RecordRuntime(self.module, self.repository)
        self.editor = type("User", (), {"username": "rita", "role": "redaktion"})()

    def server_values(self):
        return self.module.create_strategy["server_values"]

    def create(self, payload=None, operation_id="autograph-create-1"):
        return create_generic_record(
            self.repository, self.module, payload or sample_payload(), self.editor,
            self.server_values(), operation_id=operation_id,
        )

    def test_module_schema_core_types_repeaters_and_presets_are_declarative(self):
        self.assertEqual(self.module.record_type, "autograph")
        self.assertEqual(self.module.entrypoint, "generic")
        self.assertEqual(self.module.create_strategy["identity_assignment"], "on_create")
        self.assertTrue(self.module.create_strategy["show_identity_suggestion"])
        self.assertEqual(self.module.presettable_fields, ("erschliessung.altsignatur",))
        self.assertEqual(len(self.module.sections), 7)
        repeater = self.module.get_field_by_path("erschliessung.beteiligte")
        self.assertEqual(repeater.widget, "repeater")
        self.assertEqual(
            [field.path for field in repeater.item_fields],
            ["agent.type", "agent.name", "rolle", "notiz"],
        )
        self.assertEqual(
            [option["value"] for option in repeater.item_fields[0].options],
            ["person", "organization", "family"],
        )
        self.assertTrue(all(field.required for field in repeater.item_fields[:3]))
        schema = self.module.schema_path.read_text(encoding="utf-8")
        for datatype in ("agent", "place", "date_range", "term_ref"):
            self.assertIn(f"#/$defs/{datatype}", schema)

    def test_minimal_full_multiple_agents_dates_and_optional_end_validate(self):
        minimal = {
            "erschliessung": {
                "dokumenttyp": {"id": "notiz", "vocabulary_id": "autographen_dokumenttypen"},
                "erhaltungsform": {"id": "fragment", "vocabulary_id": "autographen_erhaltungsformen"},
                "beteiligte": [],
            },
        }
        first = self.create(minimal)
        self.runtime.validate(first.data)
        self.assertNotIn("datierung", first.data)

        full = self.create(sample_payload(ranged=True), operation_id="autograph-create-2")
        self.runtime.validate(full.data)
        self.assertEqual(len(full.data["erschliessung"]["beteiligte"]), 2)
        self.assertEqual(
            full.data["datierung"]["from"],
            {"year": 1875, "month": 4, "day": 12},
        )
        self.assertEqual(full.data["datierung"]["to"], {"year": 1876})
        self.assertEqual(
            full.data["erschliessung"]["interne_bemerkung"],
            "Nur intern.",
        )

        open_end = sample_payload()
        open_end["datierung"]["to"] = None
        self.runtime.validate(
            self.create(open_end, operation_id="autograph-create-3").data
        )

    def test_existing_signature_with_letter_suffix_validates(self):
        stored = self.create()

        suffix_a = deepcopy(stored.data)
        suffix_a["signatur"]["nummer"] = 102
        suffix_a["signatur"]["zusatz"] = "a"
        suffix_a["signatur"]["anzeige"] = "9.6.102a"
        self.runtime.validate(suffix_a)

        suffix_b = deepcopy(stored.data)
        suffix_b["signatur"]["nummer"] = 102
        suffix_b["signatur"]["zusatz"] = "b"
        suffix_b["signatur"]["anzeige"] = "9.6.102b"
        self.runtime.validate(suffix_b)

    def test_invalid_vocabulary_and_invalid_agent_are_rejected(self):
        unknown = sample_payload()
        unknown["erschliessung"]["dokumenttyp"]["id"] = "unbekannter-term"
        with self.assertRaises(RecordValidationError):
            self.create(unknown)

        invalid_agent = sample_payload()
        invalid_agent["erschliessung"]["beteiligte"][0]["agent"] = {"type": "person"}
        with self.assertRaises(RecordValidationError):
            self.create(invalid_agent)

    def test_internal_field_is_filtered_and_server_side_protected(self):
        stored = self.create()
        volunteer = self.runtime.filter_for_view(stored.data, "ehrenamtlich")
        self.assertNotIn("interne_bemerkung", volunteer["erschliessung"])

        for role in ("redaktion", "admin"):
            self.assertEqual(
                self.runtime.filter_for_view(
                    stored.data, role
                )["erschliessung"]["interne_bemerkung"],
                "Nur intern.",
            )
            self.assertEqual(
                self.runtime.filter_for_edit(
                    {"erschliessung": {"interne_bemerkung": "Geändert"}},
                    role,
                ),
                {"erschliessung": {"interne_bemerkung": "Geändert"}},
            )

        with self.assertRaises(RecordPermissionError):
            self.runtime.filter_for_edit(
                {"erschliessung": {"interne_bemerkung": "Manipulation"}},
                "ehrenamtlich",
            )

    def test_create_update_revision_order_and_search_use_generic_persistence(self):
        stored = self.create()
        self.assertEqual(stored.record_id, "autograph-000001")
        self.assertEqual(stored.data["signatur"]["anzeige"], "9.6.1")
        self.assertEqual(
            [
                item["agent"]["name"]
                for item in stored.data["erschliessung"]["beteiligte"]
            ],
            ["Max Mustermann", "Stift Seitenstetten"],
        )
        self.assertEqual(
            set(self.repository.commits[-1]["files"]),
            {
                "data/autographen/autograph-000001.md",
                "state/autographen-9-6.json",
                "indexes/generic/autographen-9-6.json",
            },
        )

        payload = sample_payload()
        payload["erschliessung"]["regest"] = "Geändertes Regest"
        updated = update_generic_record(
            self.repository,
            self.module,
            stored.record_id,
            payload,
            stored.revision,
            self.editor,
        )
        self.assertNotEqual(updated.revision, stored.revision)
        self.assertEqual(
            parse_record_content(
                self.repository.files[updated.path]
            )["erschliessung"]["regest"],
            "Geändertes Regest",
        )

        index = read_module_index(self.repository, self.module)
        for query in (
            "9.6.1",
            "Mustermann",
            "Brief",
            "Wien",
            "Geändertes",
            "Autogr. 42",
        ):
            self.assertEqual(
                [
                    row["record_id"]
                    for row in query_index(
                        self.module,
                        index,
                        "ehrenamtlich",
                        q=query,
                    )
                ],
                [stored.record_id],
            )

        self.assertEqual(
            query_index(
                self.module,
                index,
                "ehrenamtlich",
                q="Nur intern",
            ),
            [],
        )

    def test_module_descriptor_does_not_expose_internal_field_to_volunteer(self):
        volunteer = self.module.descriptor_for_role("ehrenamtlich")
        editor = self.module.descriptor_for_role("redaktion")

        internal_volunteer = next(
            field
            for field in volunteer["fields"]
            if field["path"] == "erschliessung.interne_bemerkung"
        )
        internal_editor = next(
            field
            for field in editor["fields"]
            if field["path"] == "erschliessung.interne_bemerkung"
        )

        self.assertFalse(internal_volunteer["visible"])
        self.assertFalse(internal_volunteer["editable"])
        self.assertTrue(internal_editor["visible"])
        self.assertTrue(internal_editor["editable"])
        self.assertNotIn(
            "erschliessung.interne_bemerkung",
            volunteer["search"]["fulltext"],
        )

    def test_generic_renderer_handles_nested_autograph_fields(self):
        node = shutil.which("node") or str(
            Path.home()
            / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
        )
        if not Path(node).exists():
            self.skipTest("Node.js required")

        subprocess.run(
            [node, "tests/autograph_form.mjs"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )


class AutographApiTest(unittest.TestCase):
    def setUp(self):
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        list_modules.cache_clear()
        self.module = get_module(MODULE_AUTOGRAPHEN_9_6)
        self.repository = repository_for(self.module)
        self.app = create_app()
        self.app.state.data_repository = self.repository
        self.app.state.generic_write_modules = {MODULE_AUTOGRAPHEN_9_6}
        self.client = TestClient(self.app)

    def login(self, role, username=None):
        username = username or f"autograph-{role}"
        with SessionLocal() as db:
            create_user(
                db,
                username=username,
                display_name=username,
                email=f"{username}@example.test",
                role=role,
                ui_profile=(
                    "ehrenamt-standard"
                    if role == "ehrenamtlich"
                    else "redaktion"
                ),
                modules=[MODULE_AUTOGRAPHEN_9_6],
                password="SehrGeheim123",
            )
            db.commit()

        response = self.client.post(
            "/api/auth/login",
            json={
                "login": username,
                "password": "SehrGeheim123",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    def csrf(self):
        name = self.client.get("/api/auth/me").json()["csrf_cookie_name"]
        return {
            "X-CSRF-Token": self.client.cookies.get(name),
        }

    def test_suggestion_does_not_reserve_and_create_assigns_final_identity(self):
        self.login("ehrenamtlich")

        state_before = self.repository.files[
            self.module.storage["state"]["path"]
        ]

        catalog_entry = next(
            item
            for item in self.client.get("/api/modules").json()
            if item["id"] == "autographen_9_6"
        )
        self.assertEqual(catalog_entry["entrypoint"], "generic")

        first = self.client.get("/api/modules/autographen_9_6")
        second = self.client.get("/api/modules/autographen_9_6")

        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(
            first.json()["empty_record"]["signatur"]["anzeige"],
            "9.6.1",
        )
        self.assertNotIn("id", first.json()["identity_suggestion"])
        self.assertEqual(
            first.json()["identity_suggestion"],
            second.json()["identity_suggestion"],
        )
        self.assertEqual(
            self.repository.files[self.module.storage["state"]["path"]],
            state_before,
        )

        response = self.client.post(
            "/api/modules/autographen_9_6/records",
            json={
                "operation_id": "api-create-1",
                "record": sample_payload(internal=False),
            },
            headers=self.csrf(),
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(
            response.json()["record"]["signatur"]["anzeige"],
            "9.6.1",
        )
        self.assertEqual(
            json.loads(
                self.repository.files[
                    self.module.storage["state"]["path"]
                ]
            )["next_signature_number"]["A"],
            2,
        )

    def test_photo_signature_suggestion_uses_selected_partition_without_reserving(self):
        photo = get_module(MODULE_FOTO_PAPIERABZUEGE)

        state = {
            "next_record_id": 12,
            "next_signature_number": {
                "A": 8,
                "B": 4,
                "C": 3,
                "D": 2,
                "E": 1,
                "F": 1,
            },
        }
        self.repository.files[
            photo.storage["state"]["path"]
        ] = json.dumps(state)

        with SessionLocal() as db:
            create_user(
                db,
                username="photo-suggestion",
                display_name="Photo",
                email=None,
                role="redaktion",
                ui_profile="redaktion",
                modules=[MODULE_FOTO_PAPIERABZUEGE],
                password="SehrGeheim123",
            )
            db.commit()

        self.client.post(
            "/api/auth/login",
            json={
                "login": "photo-suggestion",
                "password": "SehrGeheim123",
            },
        )

        before = self.repository.files[
            photo.storage["state"]["path"]
        ]

        response = self.client.get(
            f"/api/modules/{MODULE_FOTO_PAPIERABZUEGE}?signature_partition=B"
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["identity_suggestion"]["signatur.anzeige"],
            "9.4.2.B.4",
        )
        self.assertEqual(
            self.repository.files[photo.storage["state"]["path"]],
            before,
        )

    def test_autograph_write_requires_explicit_module_allowlist(self):
        self.app.state.generic_write_modules = set()
        self.login("ehrenamtlich")

        response = self.client.post(
            "/api/modules/autographen_9_6/records",
            json={
                "operation_id": "disabled-autograph",
                "record": sample_payload(internal=False),
            },
            headers=self.csrf(),
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.repository.commits, [])

    def test_volunteer_cannot_read_or_write_internal_field(self):
        stored = create_generic_record(
            self.repository,
            self.module,
            sample_payload(),
            type(
                "User",
                (),
                {
                    "username": "rita",
                    "role": "redaktion",
                },
            )(),
            self.module.create_strategy["server_values"],
            operation_id="seed-record",
        )

        self.login("ehrenamtlich")

        response = self.client.get(
            f"/api/modules/autographen_9_6/records/{stored.record_id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            "interne_bemerkung",
            response.json()["record"]["erschliessung"],
        )

        manipulated = sample_payload(internal=False)
        manipulated["erschliessung"][
            "interne_bemerkung"
        ] = "Manipulation"

        denied = self.client.post(
            "/api/modules/autographen_9_6/records",
            json={
                "operation_id": "denied-create",
                "record": manipulated,
            },
            headers=self.csrf(),
        )
        self.assertEqual(denied.status_code, 403)

    def test_vocabulary_admin_lifecycle_uses_existing_api_and_stable_term_id(self):
        self.login("redaktion")

        vocabulary_id = "autographen_beteiligtenrollen"

        current = self.client.get(
            f"/api/vocabularies/{vocabulary_id}"
        ).json()

        added = self.client.post(
            f"/api/vocabularies/{vocabulary_id}/terms",
            json={
                "base_revision": current["meta"]["revision"],
                "term": {
                    "id": "zeuge",
                    "label": "Zeuge",
                },
            },
            headers=self.csrf(),
        )
        self.assertEqual(added.status_code, 201, added.text)

        payload = sample_payload()
        payload["erschliessung"]["beteiligte"][0]["rolle"] = {
            "id": "zeuge",
            "vocabulary_id": vocabulary_id,
        }

        created = self.client.post(
            "/api/modules/autographen_9_6/records",
            json={
                "operation_id": "vocabulary-record",
                "record": payload,
            },
            headers=self.csrf(),
        )
        self.assertEqual(created.status_code, 201, created.text)

        renamed = self.client.patch(
            f"/api/vocabularies/{vocabulary_id}/terms/zeuge",
            json={
                "base_revision": added.json()["meta"]["revision"],
                "label": "Bezeugende Person",
            },
            headers=self.csrf(),
        )
        self.assertEqual(renamed.status_code, 200, renamed.text)

        deactivated = self.client.patch(
            f"/api/vocabularies/{vocabulary_id}/terms/zeuge",
            json={
                "base_revision": renamed.json()["meta"]["revision"],
                "active": False,
            },
            headers=self.csrf(),
        )
        self.assertEqual(
            deactivated.status_code,
            200,
            deactivated.text,
        )

        term = next(
            item
            for item in deactivated.json()["vocabulary"]["terms"]
            if item["id"] == "zeuge"
        )
        self.assertEqual(term["label"], "Bezeugende Person")
        self.assertFalse(term["active"])

        record = self.client.get(
            f"/api/modules/autographen_9_6/records/"
            f"{created.json()['record_id']}"
        ).json()["record"]

        self.assertEqual(
            record["erschliessung"]["beteiligte"][0]["rolle"]["id"],
            "zeuge",
        )


if __name__ == "__main__":
    unittest.main()
