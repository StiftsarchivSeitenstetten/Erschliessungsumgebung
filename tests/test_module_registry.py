import unittest

from backend.modules import CORE_DATATYPES, get_module, list_datatypes, list_modules


class ModuleRegistryTest(unittest.TestCase):
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
        self.assertIn("beschriftung", module.form_fields)
        self.assertIn("id", module.search_fields)
        self.assertEqual(module.signature_strategy["bestand"], "9.4")

    def test_registry_allows_lookup_by_internal_module_id(self):
        module = get_module("papierabzuege_9_4_2")
        self.assertEqual(module.access_key, "foto_papierabzuege")
        self.assertIn(module, list_modules())

    def test_field_rights_are_derived_by_role_not_visual_profile(self):
        module = get_module("foto_papierabzuege")
        self.assertEqual(module.field_rights["titel"]["write"], ["redaktion"])
        self.assertIn("ehrenamtlich", module.field_rights["beschriftung"]["write"])
        self.assertIn("redaktion", module.field_rights["beschriftung"]["write"])


if __name__ == "__main__":
    unittest.main()
