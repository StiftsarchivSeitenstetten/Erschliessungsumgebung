import unittest
from copy import deepcopy
from pathlib import Path
import tempfile

import yaml

from backend.modules import (
    CORE_DATATYPES,
    ModuleConfigError,
    get_module,
    list_datatypes,
    list_modules,
    load_module,
    load_modules,
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
        self.assertTrue(module.schema_path.name.endswith("foto.schema.json"))
        self.assertIn("erschliessung.beschriftung", module.form_fields)
        self.assertIn("id", module.search_fields)
        self.assertEqual(module.signature_strategy["bestand"], "9.4")

    def test_registry_allows_lookup_by_internal_module_id(self):
        module = get_module("papierabzuege_9_4_2")
        self.assertEqual(module.access_key, "foto_papierabzuege")
        self.assertIn(module, list_modules())

    def test_field_rights_are_derived_by_role_not_visual_profile(self):
        module = get_module("foto_papierabzuege")
        self.assertEqual(module.field_rights["erschliessung.titel"]["edit"], ["redaktion", "admin"])
        self.assertIn("ehrenamtlich", module.field_rights["erschliessung.beschriftung"]["edit"])
        self.assertIn("redaktion", module.field_rights["erschliessung.beschriftung"]["edit"])

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
