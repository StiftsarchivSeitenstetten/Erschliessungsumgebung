"""Isolated module, loaded only by explicitly started integration tests."""

import json
from pathlib import Path

from backend.modules import load_module


MODULE_KEY = "generic_integration_test"
DATA_DIR = "data/integration-test"
STATE_PATH = "state/integration-test.json"
APP_ROOT = Path(__file__).resolve().parents[1]


def make_module(directory: Path):
    roles = ["ehrenamtlich", "redaktion", "admin"]
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object", "additionalProperties": False,
        "required": ["id", "datensatz_typ", "signatur", "daten", "technik"],
        "properties": {
            "id": {"type": "string", "pattern": "^integration-[0-9]{4,}$"},
            "datensatz_typ": {"const": MODULE_KEY},
            "signatur": {
                "type": "object", "additionalProperties": False,
                "required": ["format", "nummer", "anzeige", "status"],
                "properties": {
                    "format": {"const": "T"}, "nummer": {"type": "integer", "minimum": 1},
                    "anzeige": {"type": "string"}, "status": {"const": "vergeben"},
                },
            },
            "daten": {
                "type": "object", "additionalProperties": False,
                "required": ["text", "personen", "zeitraum"],
                "properties": {
                    "text": {"type": "string", "minLength": 1},
                    "intern": {"type": "string"},
                    "personen": {"type": "array", "items": {
                        "type": "object", "additionalProperties": False,
                        "required": ["name"], "properties": {"name": {"type": "string"}},
                    }},
                    "zeitraum": {"$ref": "https://stiftsarchiv-seitenstetten.github.io/erschliessungsumgebung/schemas/core-datatypes.schema.json#/$defs/date_range"},
                    "dokumenttyp": {"$ref": "https://stiftsarchiv-seitenstetten.github.io/erschliessungsumgebung/schemas/core-datatypes.schema.json#/$defs/term_ref"},
                    "funktion": {"$ref": "https://stiftsarchiv-seitenstetten.github.io/erschliessungsumgebung/schemas/core-datatypes.schema.json#/$defs/term_ref"},
                },
            },
            "technik": {
                "type": "object", "additionalProperties": False,
                "required": ["erstellt_am", "erstellt_von", "geaendert_am", "geaendert_von"],
                "properties": {key: {"type": ["string", "null"]} for key in (
                    "erstellt_am", "erstellt_von", "geaendert_am", "geaendert_von",
                )},
            },
        },
    }
    schema_path = directory / "integration.schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")
    fields = [
        {"path": "signatur.anzeige", "widget": "text", "label": "Testsignatur", "order": 0},
        {"path": "daten.text", "widget": "text", "label": "Testtext", "order": 10, "presettable": True},
        {"path": "daten.personen", "widget": "repeater", "label": "Testpersonen", "order": 20,
         "presettable": True,
         "item_fields": [{"path": "name", "widget": "text", "label": "Name", "order": 0}]},
        {"path": "daten.zeitraum", "widget": "date_range", "label": "Testzeitraum", "order": 30, "presettable": True},
        {"path": "daten.intern", "widget": "text", "label": "Redaktioneller Testwert", "order": 40},
        {"path": "daten.dokumenttyp", "widget": "vocabulary_select", "vocabulary": "dokumenttypen",
         "label": "Dokumenttyp", "order": 50, "presettable": True},
        {"path": "daten.funktion", "widget": "vocabulary_select", "vocabulary": "rollen",
         "label": "Rolle", "order": 60},
    ]
    rights = {field["path"]: {"view": roles, "edit": roles} for field in fields}
    rights["signatur.anzeige"]["edit"] = []
    rights["daten.intern"] = {"view": ["redaktion", "admin"], "edit": ["redaktion", "admin"]}
    config = {
        "config_version": 1,
        "module": {"id": MODULE_KEY, "access_key": MODULE_KEY,
                   "label": "Isolierter GitHub-Integrationstest", "record_type": MODULE_KEY},
        "schema": {"path": str(schema_path)},
        "storage": {"data_dir": DATA_DIR, "filename": {"strategy": "record_id_with_extension", "extension": ".md"},
                    "state": {"path": STATE_PATH}},
        "id": {"strategy": "prefixed_sequence", "prefix": "integration-", "width": 4},
        "signature": {"strategy": "partitioned_sequence", "partitions": ["T"],
                      "pattern": "INTEGRATION.{partition}.{number}", "status_values": ["vergeben"]},
        "create": {"identity_assignment": "on_create"},
        "form": {"sections": [{"id": "test", "label": "Integrationstest", "order": 0, "fields": fields}]},
        "access": {"fields": rights}, "search": {"fulltext": ["daten.text"], "filters": []},
        "list": {"columns": [{"label": "Testtext", "path": "daten.text"}]},
        "presets": {"enabled_fields": ["daten.text", "daten.personen", "daten.zeitraum", "daten.dokumenttyp"], "disabled_fields": []},
        "vocabularies": {
            "dokumenttypen": {"path": str(APP_ROOT / "vocabularies" / "dokumenttypen.yaml")},
            "rollen": {"path": str(APP_ROOT / "vocabularies" / "rollen.yaml")},
        },
    }
    module_path = directory / "integration.yaml"
    module_path.write_text(json.dumps(config), encoding="utf-8")
    return load_module(module_path)


def sample_payload():
    return {"daten": {
        "text": "GENERIC INTEGRATION TEST - kein Archivdatensatz",
        "personen": [{"name": "Testperson Eins"}, {"name": "Testperson Zwei"}],
        "zeitraum": {"from": {"year": 1900}, "to": {"year": 1901}, "display": "1900-1901"},
        "intern": "Nur redaktionell sichtbarer Integrationstestwert",
        "dokumenttyp": {"id": "brief", "vocabulary_id": "dokumenttypen"},
        "funktion": {"id": "absender", "vocabulary_id": "rollen"},
    }}
