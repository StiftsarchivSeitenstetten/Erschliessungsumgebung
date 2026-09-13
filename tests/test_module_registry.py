import unittest
from copy import deepcopy
from pathlib import Path
import tempfile

import yaml

from backend.modules import (
    CORE_DATATYPES,
    ModuleConfigError,
    get_path_value,
    get_module,
    path_exists,
    list_datatypes,
    list_modules,
    load_module,
    load_modules,
    set_path_value,
    validate_core_schemas,
    validate_vocabulary,
)


ROOT = Path(__file__).resolve().parents[1]
PHOTO_MODULE_PATH = ROOT / "ui" / "modules" / "papierabzuege.yaml"


def valid_module_config() -> dict:
    data = yaml.safe_load(PHOTO_MODULE_PATH.read_text(encoding="utf-8"))
    data["schema"]["path"] = str(ROOT / "schemas" / "foto.schema.json")
    return data


def write_module_config(directory: Path, name: str, data: dict) -> Path:
    path = directory / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def architecture_test_config() -> dict:
    data = valid_module_config()
    data["module"] = {
        "id": "testmodul",
        "access_key": "testmodul",
        "label": "Testmodul",
        "description": "Nur fuer Architekturtests.",
        "record_type": "test",
    }
    data["id"] = {"strategy": "prefixed_sequence", "prefix": "test-", "width": 4}
    data["storage"]["data_dir"] = "data/test"
    data["storage"]["state"]["path"] = "state/test.json"
    data["storage"]["index"]["path"] = "indexes/test.json"
    data["signature"] = {"strategy": "partitioned_sequence", "partitions": ["A"], "pattern": "T.{nummer}", "status_values": ["vergeben"]}
    data["form"] = {
        "sections": [{
            "id": "main",
            "label": "Main",
            "order": 10,
            "fields": [
                {"id": "name", "path": "daten.name", "widget": "text", "label": "Name", "order": 10, "presettable": True},
                {"id": "readonly", "path": "daten.readonly", "widget": "textarea", "label": "Nur lesbar", "order": 20, "rows": 2},
                {"id": "secret", "path": "daten.secret", "widget": "text", "label": "Geheim", "order": 30},
                {
                    "id": "beteiligte",
                    "path": "daten.beteiligte",
                    "widget": "repeater",
                    "label": "Beteiligte",
                    "order": 40,
                    "item_fields": [
                        {"id": "akteur", "path": "akteur", "widget": "text", "label": "Akteur", "order": 10},
                        {"id": "rolle", "path": "rolle", "widget": "vocabulary_select", "label": "Rolle", "order": 20, "vocabulary": "rollen"},
                    ],
                },
                {"id": "zeitraum", "path": "daten.zeitraum", "widget": "date_range", "label": "Zeitraum", "order": 50},
                {"id": "erstellt_am", "path": "technik.erstellt_am", "widget": "text", "label": "Erstellt am", "order": 60},
            ],
        }]
    }
    data["access"] = {
        "fields": {
            "daten.name": {"view": ["ehrenamtlich", "redaktion", "admin"], "edit": ["ehrenamtlich", "redaktion", "admin"]},
            "daten.readonly": {"view": ["ehrenamtlich", "redaktion", "admin"], "edit": ["redaktion", "admin"]},
            "daten.secret": {"view": ["redaktion", "admin"], "edit": ["redaktion", "admin"]},
            "daten.beteiligte": {"view": ["ehrenamtlich", "redaktion", "admin"], "edit": ["redaktion", "admin"]},
            "daten.zeitraum": {"view": ["ehrenamtlich", "redaktion", "admin"], "edit": ["redaktion", "admin"]},
            "technik.erstellt_am": {"view": ["admin"], "edit": ["admin"]},
        }
    }
    data["search"] = {"fulltext": ["daten.name"], "filters": [{"path": "daten.zeitraum", "label": "Zeitraum", "widget": "date_range"}]}
    data["list"] = {"columns": [{"label": "Name", "path": "daten.name", "sortable": True}]}
    data["presets"] = {"enabled_fields": ["daten.name"], "disabled_fields": ["technik"]}
    data["vocabularies"] = {"rollen": {"path": "../../vocabularies/redaktionsstufen.yaml"}}
    data["ui_profiles"] = {"standard": {"label": "Standard"}}
    data.pop("formats", None)
    data.pop("form_fields", None)
    data.pop("search_fields", None)
    data.pop("list_fields", None)
    return data


class ModuleRegistryTest(unittest.TestCase):
    def test_configuration_schemas_are_valid_json_schema(self):
        validate_core_schemas()

    def test_core_datatypes_v1_are_registered(self):
        keys = {datatype.key for datatype in list_datatypes()}
        self.assertEqual(keys, {
            "agent",
            "place",
            "date",
            "date_range",
            "term_ref",
            "identifier",
            "record_ref",
            "digital_asset",
            "language",
        })
        self.assertEqual(CORE_DATATYPES["agent"].label, "Akteur")

    def test_photo_module_is_loaded_from_declarative_configuration(self):
        module = get_module("foto_papierabzuege")
        self.assertEqual(module.id, "papierabzuege_9_4_2")
        self.assertEqual(module.access_key, "foto_papierabzuege")
        self.assertEqual(module.datensatz_typ, "foto")
        self.assertEqual(module.record_type, "foto")
        self.assertTrue(module.schema_path.name.endswith("foto.schema.json"))
        self.assertIn("erschliessung.beschriftung", module.form_fields)
        self.assertIn("id", module.search_fields)
        self.assertEqual(module.signature_strategy["bestand"], "9.4")
        self.assertEqual(module.storage["data_dir"], "data/fotos")

    def test_registry_allows_lookup_by_internal_module_id(self):
        module = get_module("papierabzuege_9_4_2")
        self.assertEqual(module.access_key, "foto_papierabzuege")
        self.assertIn(module, list_modules())

    def test_field_rights_are_derived_by_role_not_visual_profile(self):
        module = get_module("foto_papierabzuege")
        self.assertEqual(module.field_rights["erschliessung.titel"]["edit"], ["redaktion", "admin"])
        self.assertIn("ehrenamtlich", module.field_rights["erschliessung.beschriftung"]["edit"])
        self.assertIn("redaktion", module.field_rights["erschliessung.beschriftung"]["edit"])

    def test_photo_runtime_model_exposes_sections_fields_and_descriptor(self):
        module = get_module("foto_papierabzuege")
        self.assertEqual([section.id for section in module.sections], ["identifikation", "erschliessung", "datierung", "merkmale"])
        beschriftung = module.get_field("beschriftung")
        self.assertEqual(beschriftung.path, "erschliessung.beschriftung")
        self.assertEqual(module.get_field_by_path("erschliessung.beschriftung").id, "beschriftung")
        self.assertEqual(module.get_field("dargestellte_personen").widget, "repeater")
        self.assertTrue(module.get_field("beschreibung").presettable)
        self.assertIn("signatur.anzeige", module.search_config["fulltext"])
        self.assertEqual(module.list_config["columns"][0]["path"], "signatur.anzeige")
        self.assertIn("standard", module.ui_profiles)

        descriptor = module.descriptor_for_role("ehrenamtlich")
        title = next(field for field in descriptor["fields"] if field["id"] == "titel")
        beschriftung_descriptor = next(field for field in descriptor["fields"] if field["id"] == "beschriftung")
        self.assertFalse(title["visible"])
        self.assertFalse(title["editable"])
        self.assertTrue(beschriftung_descriptor["visible"])
        self.assertTrue(beschriftung_descriptor["editable"])

    def test_runtime_model_supports_generic_architecture_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_module_config(Path(tmp), "test.yaml", architecture_test_config())
            module = load_module(path)
        self.assertEqual(module.get_field("name").path, "daten.name")
        self.assertEqual(module.get_field_by_path("daten.secret").id, "secret")
        self.assertTrue(module.can_view_field("secret", "redaktion"))
        self.assertFalse(module.can_view_field("secret", "ehrenamtlich"))
        self.assertFalse(module.can_edit_field("readonly", "ehrenamtlich"))
        self.assertTrue(module.can_view_field("readonly", "ehrenamtlich"))
        repeater = module.get_field("beteiligte")
        self.assertEqual(repeater.widget, "repeater")
        self.assertEqual(repeater.item_fields[1].widget, "vocabulary_select")
        self.assertEqual(module.get_field("zeitraum").widget, "date_range")

    def test_server_managed_fields_are_not_editable_even_if_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_module_config(Path(tmp), "test.yaml", architecture_test_config())
            module = load_module(path)
        self.assertTrue(module.can_view_field("erstellt_am", "admin"))
        self.assertFalse(module.can_edit_field("erstellt_am", "admin"))

    def test_path_helpers_read_write_and_create_nested_objects(self):
        record = {"erschliessung": {"beschriftung": "Alt"}}
        self.assertEqual(get_path_value(record, "erschliessung.beschriftung"), "Alt")
        self.assertTrue(path_exists(record, "erschliessung.beschriftung"))
        self.assertFalse(path_exists(record, "technik.erstellt_am"))
        set_path_value(record, "technik.erstellt_am", "2026-09-13T00:00:00Z")
        self.assertEqual(record["technik"]["erstellt_am"], "2026-09-13T00:00:00Z")

    def test_edit_without_view_is_rejected(self):
        data = architecture_test_config()
        data["access"]["fields"]["daten.secret"] = {"view": ["redaktion"], "edit": ["redaktion", "admin"]}
        with tempfile.TemporaryDirectory() as tmp:
            path = write_module_config(Path(tmp), "invalid.yaml", data)
            with self.assertRaises(ModuleConfigError):
                load_module(path)

    def test_invalid_config_version_is_rejected(self):
        data = valid_module_config()
        data["config_version"] = 2
        with tempfile.TemporaryDirectory() as tmp:
            path = write_module_config(Path(tmp), "invalid.yaml", data)
            with self.assertRaises(ModuleConfigError):
                load_module(path)

    def test_unknown_role_is_rejected(self):
        data = valid_module_config()
        data["access"]["fields"]["erschliessung.beschriftung"]["edit"] = ["praktikant"]
        with tempfile.TemporaryDirectory() as tmp:
            path = write_module_config(Path(tmp), "invalid.yaml", data)
            with self.assertRaises(ModuleConfigError):
                load_module(path)

    def test_unknown_widget_is_rejected(self):
        data = valid_module_config()
        data["form"]["sections"][1]["fields"][0]["widget"] = "magic_widget"
        with tempfile.TemporaryDirectory() as tmp:
            path = write_module_config(Path(tmp), "invalid.yaml", data)
            with self.assertRaises(ModuleConfigError):
                load_module(path)

    def test_duplicate_module_id_is_rejected(self):
        first = valid_module_config()
        second = deepcopy(first)
        second["module"]["access_key"] = "zweiter_zugriff"
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            first_path = write_module_config(tmp_path, "one.yaml", first)
            second_path = write_module_config(tmp_path, "two.yaml", second)
            with self.assertRaises(ModuleConfigError):
                load_modules((first_path, second_path))

    def test_invalid_vocabulary_is_rejected(self):
        with self.assertRaises(ModuleConfigError):
            validate_vocabulary({
                "id": "rollen",
                "label": "Rollen",
                "terms": [{"id": "autor", "label": "Autor"}],
            })


if __name__ == "__main__":
    unittest.main()
