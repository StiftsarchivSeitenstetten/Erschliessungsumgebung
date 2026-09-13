from dataclasses import dataclass
from pathlib import Path
import tempfile
import unittest

import yaml

from backend.modules import load_module
from backend.records.runtime import RecordPermissionError, RecordRuntime, RecordValidationError


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RuntimeUser:
    username: str
    role: str


def write_runtime_schema(directory: Path) -> Path:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://example.test/schemas/runtime-test.schema.json",
        "type": "object",
        "additionalProperties": False,
        "required": ["id", "datensatz_typ", "daten", "technik"],
        "properties": {
            "id": {"type": "string"},
            "datensatz_typ": {"const": "test"},
            "daten": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "name",
                    "agent",
                    "place",
                    "date",
                    "date_range",
                    "term",
                    "identifier",
                    "record",
                    "asset",
                    "language",
                    "beteiligte",
                ],
                "properties": {
                    "name": {"type": "string"},
                    "readonly": {"type": ["string", "null"]},
                    "secret": {"type": ["string", "null"]},
                    "agent": {"$ref": "https://stiftsarchiv-seitenstetten.github.io/erschliessungsumgebung/schemas/core-datatypes.schema.json#/$defs/agent"},
                    "place": {"$ref": "https://stiftsarchiv-seitenstetten.github.io/erschliessungsumgebung/schemas/core-datatypes.schema.json#/$defs/place"},
                    "date": {"$ref": "https://stiftsarchiv-seitenstetten.github.io/erschliessungsumgebung/schemas/core-datatypes.schema.json#/$defs/date"},
                    "date_range": {"$ref": "https://stiftsarchiv-seitenstetten.github.io/erschliessungsumgebung/schemas/core-datatypes.schema.json#/$defs/date_range"},
                    "term": {"$ref": "https://stiftsarchiv-seitenstetten.github.io/erschliessungsumgebung/schemas/core-datatypes.schema.json#/$defs/term_ref"},
                    "identifier": {"$ref": "https://stiftsarchiv-seitenstetten.github.io/erschliessungsumgebung/schemas/core-datatypes.schema.json#/$defs/identifier"},
                    "record": {"$ref": "https://stiftsarchiv-seitenstetten.github.io/erschliessungsumgebung/schemas/core-datatypes.schema.json#/$defs/record_ref"},
                    "asset": {"$ref": "https://stiftsarchiv-seitenstetten.github.io/erschliessungsumgebung/schemas/core-datatypes.schema.json#/$defs/digital_asset"},
                    "language": {"$ref": "https://stiftsarchiv-seitenstetten.github.io/erschliessungsumgebung/schemas/core-datatypes.schema.json#/$defs/language"},
                    "beteiligte": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["name"],
                            "properties": {
                                "name": {"type": "string"},
                                "rolle": {"type": ["string", "null"]},
                            },
                        },
                    },
                },
            },
            "technik": {
                "type": "object",
                "additionalProperties": False,
                "required": ["erstellt_am", "erstellt_von", "geaendert_am", "geaendert_von"],
                "properties": {
                    "erstellt_am": {"type": ["string", "null"]},
                    "erstellt_von": {"type": ["string", "null"]},
                    "geaendert_am": {"type": ["string", "null"]},
                    "geaendert_von": {"type": ["string", "null"]},
                },
            },
        },
    }
    path = directory / "runtime-test.schema.json"
    import json
    path.write_text(json.dumps(schema), encoding="utf-8")
    return path


def write_runtime_module(directory: Path, schema_path: Path) -> Path:
    editable = ["ehrenamtlich", "redaktion", "admin"]
    redaktion = ["redaktion", "admin"]
    fields = [
        {"id": "name", "path": "daten.name", "widget": "text", "label": "Name", "order": 10, "presettable": True},
        {"id": "readonly", "path": "daten.readonly", "widget": "text", "label": "Nur lesbar", "order": 20},
        {"id": "secret", "path": "daten.secret", "widget": "text", "label": "Geheim", "order": 30},
        {"id": "agent", "path": "daten.agent", "widget": "text", "label": "Agent", "order": 40},
        {"id": "place", "path": "daten.place", "widget": "text", "label": "Ort", "order": 50},
        {"id": "date", "path": "daten.date", "widget": "date", "label": "Datum", "order": 60},
        {"id": "date_range", "path": "daten.date_range", "widget": "date_range", "label": "Zeitraum", "order": 70},
        {"id": "term", "path": "daten.term", "widget": "vocabulary_select", "label": "Begriff", "order": 80, "vocabulary": "terms", "options": [
            {"value": "brief", "label": "Brief"},
            {"value": "foto", "label": "Foto"},
        ]},
        {"id": "identifier", "path": "daten.identifier", "widget": "text", "label": "Kennung", "order": 90},
        {"id": "record", "path": "daten.record", "widget": "text", "label": "Datensatz", "order": 100},
        {"id": "asset", "path": "daten.asset", "widget": "text", "label": "Digitalisat", "order": 110},
        {"id": "language", "path": "daten.language", "widget": "select", "label": "Sprache", "order": 120, "options": [
            {"value": "de", "label": "Deutsch"},
            {"value": "la", "label": "Latein"},
        ]},
        {
            "id": "beteiligte",
            "path": "daten.beteiligte",
            "widget": "repeater",
            "label": "Beteiligte",
            "order": 130,
            "item_fields": [
                {"id": "name", "path": "name", "widget": "text", "label": "Name", "order": 10},
                {"id": "rolle", "path": "rolle", "widget": "vocabulary_select", "label": "Rolle", "order": 20, "vocabulary": "terms", "options": [
                    {"value": "absender", "label": "Absender"},
                    {"value": "empfaenger", "label": "Empfänger"},
                ]},
            ],
        },
    ]
    access = {
        "daten.name": {"view": editable, "edit": editable},
        "daten.readonly": {"view": editable, "edit": redaktion},
        "daten.secret": {"view": redaktion, "edit": redaktion},
        "daten.agent": {"view": editable, "edit": editable},
        "daten.place": {"view": editable, "edit": editable},
        "daten.date": {"view": editable, "edit": editable},
        "daten.date_range": {"view": editable, "edit": editable},
        "daten.term": {"view": editable, "edit": editable},
        "daten.identifier": {"view": editable, "edit": editable},
        "daten.record": {"view": editable, "edit": editable},
        "daten.asset": {"view": editable, "edit": editable},
        "daten.language": {"view": editable, "edit": editable},
        "daten.beteiligte": {"view": editable, "edit": editable},
        "technik.erstellt_am": {"view": ["admin"], "edit": ["admin"]},
    }
    module = {
        "config_version": 1,
        "module": {"id": "runtime_test", "access_key": "runtime_test", "label": "Runtime Test", "record_type": "test"},
        "schema": {"path": str(schema_path)},
        "storage": {"data_dir": "data/test", "filename": {"strategy": "record_id_with_extension", "extension": ".md"}},
        "id": {"strategy": "prefixed_sequence", "prefix": "test-", "width": 4},
        "signature": {"strategy": "partitioned_sequence", "partitions": ["A"], "pattern": "T.{nummer}", "status_values": ["vergeben"]},
        "form": {"sections": [{"id": "main", "label": "Main", "order": 10, "fields": fields}]},
        "access": {"fields": access},
        "search": {"fulltext": ["daten.name"], "filters": []},
        "list": {"columns": [
            {"label": "Name", "path": "daten.name", "sortable": True},
            {"label": "Geheim", "path": "daten.secret", "sortable": False},
        ]},
        "presets": {"enabled_fields": ["daten.name"], "disabled_fields": ["technik"]},
    }
    path = directory / "runtime-test.yaml"
    path.write_text(yaml.safe_dump(module, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def valid_payload() -> dict:
    return {
        "daten": {
            "name": "Test",
            "agent": {"type": "person", "name": "Muster, Maria"},
            "place": {"name": "Seitenstetten", "coordinates": {"lat": 48.0, "lon": 14.0}},
            "date": {"year": 1900, "display": "um 1900", "certainty": "approximate"},
            "date_range": {"from": {"year": 1900}, "to": {"year": 1901}, "display": "1900/1901"},
            "term": {"id": "brief", "vocabulary_id": "terms"},
            "identifier": {"value": "ALT-1", "type": "altsignatur"},
            "record": {"record_id": "foto-000001", "module_id": "foto_papierabzuege", "label": "Referenz"},
            "asset": {"path": "digitalisate/test.jpg", "mime_type": "image/jpeg", "filename": "test.jpg"},
            "language": {"code": "de"},
            "beteiligte": [{"name": "A"}, {"name": "B", "rolle": "empfaenger"}],
        }
    }


class RecordRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        root = Path(self.tempdir.name)
        self.schema_path = write_runtime_schema(root)
        self.module_path = write_runtime_module(root, self.schema_path)
        self.module = load_module(self.module_path)
        self.runtime = RecordRuntime(self.module)
        self.ehrenamt = RuntimeUser(username="anna", role="ehrenamtlich")
        self.redaktion = RuntimeUser(username="rita", role="redaktion")

    def tearDown(self):
        self.tempdir.cleanup()

    def create_record(self) -> dict:
        return self.runtime.prepare_create(
            valid_payload(),
            self.ehrenamt,
            server_values={"id": "test-0001", "datensatz_typ": "test"},
        )

    def test_prepare_create_validates_schema_and_sets_technical_metadata(self):
        record = self.create_record()
        self.assertEqual(record["id"], "test-0001")
        self.assertEqual(record["datensatz_typ"], "test")
        self.assertIsNotNone(record["technik"]["erstellt_am"])
        self.assertEqual(record["technik"]["erstellt_von"], "anna")
        self.assertIsNone(record["technik"]["geaendert_am"])
        self.assertIsNone(record["technik"]["geaendert_von"])

    def test_filter_for_view_hides_invisible_field(self):
        record = self.create_record()
        record["daten"]["secret"] = "intern"
        visible = self.runtime.filter_for_view(record, "ehrenamtlich")
        self.assertNotIn("secret", visible["daten"])
        self.assertEqual(visible["daten"]["name"], "Test")
        self.assertIn("id", visible)

    def test_readonly_field_cannot_be_written_by_role(self):
        with self.assertRaises(RecordPermissionError):
            self.runtime.filter_for_edit({"daten": {"readonly": "Nein"}}, "ehrenamtlich")

    def test_server_managed_field_cannot_be_written(self):
        with self.assertRaises(RecordPermissionError):
            self.runtime.filter_for_edit({"technik": {"erstellt_am": "manipuliert"}}, "admin")

    def test_unknown_field_is_rejected(self):
        with self.assertRaises(RecordPermissionError):
            self.runtime.filter_for_edit({"daten": {"unbekannt": "x"}}, "redaktion")

    def test_nested_field_and_repeater_are_preserved(self):
        record = self.create_record()
        self.assertEqual(record["daten"]["place"]["name"], "Seitenstetten")
        self.assertEqual(len(record["daten"]["beteiligte"]), 2)

    def test_invalid_repeater_entry_fails_schema_validation(self):
        payload = valid_payload()
        payload["daten"]["beteiligte"] = [{"rolle": "ohne name"}]
        with self.assertRaises(RecordValidationError):
            self.runtime.prepare_create(payload, self.ehrenamt, server_values={"id": "test-0001", "datensatz_typ": "test"})

    def test_update_applies_allowed_changes_and_change_metadata(self):
        existing = self.create_record()
        updated = self.runtime.prepare_update(existing, {"daten": {"name": "Neu"}}, self.redaktion)
        self.assertEqual(updated["daten"]["name"], "Neu")
        self.assertEqual(updated["technik"]["erstellt_von"], "anna")
        self.assertIsNotNone(updated["technik"]["geaendert_am"])
        self.assertEqual(updated["technik"]["geaendert_von"], "rita")

    def test_core_datatypes_are_validated(self):
        record = self.create_record()
        self.runtime.validate(record)
        record["daten"]["agent"] = {"type": "person"}
        with self.assertRaises(RecordValidationError):
            self.runtime.validate(record)

    def test_photo_module_can_be_used_by_generic_runtime(self):
        from backend.modules import get_module

        photo_runtime = RecordRuntime(get_module("foto_papierabzuege"))
        self.assertIn("erschliessung.beschriftung", photo_runtime.fields_by_path)
        self.assertTrue(photo_runtime.module.can_edit_field("erschliessung.beschriftung", "ehrenamtlich"))
        self.assertFalse(photo_runtime.module.can_view_field("erschliessung.titel", "ehrenamtlich"))


if __name__ == "__main__":
    unittest.main()
