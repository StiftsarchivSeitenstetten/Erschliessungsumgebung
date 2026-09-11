from pathlib import Path
import unittest

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from foto_core import (  # noqa: E402
    LOCAL_RECORDS_KEY,
    LocalPilotSession,
    append_local_record,
    archivis_date_value,
    build_signature,
    load_config,
    load_records,
    next_number,
    reset_local_session_storage,
    validate_record_schema,
    validate_collection,
)


class FotoCoreTest(unittest.TestCase):
    def setUp(self):
        self.config = load_config()

    def test_signature_building(self):
        self.assertEqual(
            build_signature("C", 505)["anzeige"],
            "9.4.2.C.505",
        )

    def test_next_number_per_format(self):
        records = [
            {"signatur": {"format": "A", "nummer": 8610}},
            {"signatur": {"format": "B", "nummer": 1025}},
            {"signatur": {"format": "C", "nummer": 504}},
        ]
        self.assertEqual(next_number(records, "A"), 8611)
        self.assertEqual(next_number(records, "B"), 1026)
        self.assertEqual(next_number(records, "C"), 505)

    def test_local_session_advances_same_format(self):
        records = [
            {"id": "foto-000001", "signatur": {"format": "A", "nummer": 8610}},
        ]
        first = append_local_record(records, "A")
        second = append_local_record(records, "A")
        third = append_local_record(records, "A")
        self.assertEqual(first["id"], "foto-000002")
        self.assertEqual(second["id"], "foto-000003")
        self.assertEqual(third["id"], "foto-000004")
        self.assertEqual(first["signatur"]["anzeige"], "9.4.2.A.8611")
        self.assertEqual(second["signatur"]["anzeige"], "9.4.2.A.8612")
        self.assertEqual(third["signatur"]["anzeige"], "9.4.2.A.8613")

    def test_local_session_advances_independent_formats(self):
        records = [
            {"id": "foto-000001", "signatur": {"format": "A", "nummer": 8468}},
            {"id": "foto-000002", "signatur": {"format": "B", "nummer": 1025}},
            {"id": "foto-000003", "signatur": {"format": "C", "nummer": 500}},
        ]
        a = append_local_record(records, "A")
        b = append_local_record(records, "B")
        c = append_local_record(records, "C")
        a_again = append_local_record(records, "A")
        self.assertEqual(a["signatur"]["anzeige"], "9.4.2.A.8469")
        self.assertEqual(b["signatur"]["anzeige"], "9.4.2.B.1026")
        self.assertEqual(c["signatur"]["anzeige"], "9.4.2.C.501")
        self.assertEqual(a_again["signatur"]["anzeige"], "9.4.2.A.8470")

    def test_repeated_preview_does_not_consume_id_or_signature(self):
        session = LocalPilotSession(
            inventory=[{"id": "foto-000001", "signatur": {"format": "A", "nummer": 8468}}],
            config=self.config,
        )
        first = session.preview("A")
        second = session.preview("A")
        third = session.preview("A")
        self.assertEqual(first["id"], "foto-000002")
        self.assertEqual(second["id"], "foto-000002")
        self.assertEqual(third["id"], "foto-000002")
        self.assertEqual(first["signatur"]["anzeige"], "9.4.2.A.8469")
        self.assertEqual(second["signatur"]["anzeige"], "9.4.2.A.8469")
        self.assertEqual(third["signatur"]["anzeige"], "9.4.2.A.8469")
        self.assertEqual(len(session.inventory), 1)

    def test_correction_after_preview_keeps_number(self):
        session = LocalPilotSession(
            inventory=[{"id": "foto-000001", "signatur": {"format": "C", "nummer": 500}}],
            config=self.config,
        )
        before_correction = session.preview("C")
        # Form corrections do not touch the technical draft.
        after_correction = session.preview("C")
        self.assertIs(before_correction, after_correction)
        self.assertEqual(after_correction["id"], "foto-000002")
        self.assertEqual(after_correction["signatur"]["anzeige"], "9.4.2.C.501")

    def test_finalize_consumes_number_once(self):
        session = LocalPilotSession(
            inventory=[{"id": "foto-000001", "signatur": {"format": "B", "nummer": 1025}}],
            config=self.config,
        )
        draft = session.preview("B")
        finalized = session.finalize()
        self.assertEqual(finalized, draft)
        self.assertEqual(len(session.inventory), 2)
        with self.assertRaises(ValueError):
            session.finalize()
        self.assertEqual(len(session.inventory), 2)

    def test_new_record_after_finalize_uses_next_number(self):
        session = LocalPilotSession(
            inventory=[{"id": "foto-000001", "signatur": {"format": "A", "nummer": 8468}}],
            config=self.config,
        )
        session.preview("A")
        session.finalize()
        session.new_record()
        next_draft = session.preview("A")
        self.assertEqual(next_draft["id"], "foto-000003")
        self.assertEqual(next_draft["signatur"]["anzeige"], "9.4.2.A.8470")

    def test_reset_local_session_inventory_keeps_preset(self):
        preset_key = "erschliessung.papierabzuege.activePreset.v2"
        profile_key = "erschliessung.papierabzuege.profile"
        storage = {
            LOCAL_RECORDS_KEY: [{"id": "foto-000099", "format": "A", "nummer": 9000}],
            preset_key: {"values": {"herkunft": "Fotofaszikel Albert Kurzwernhart"}},
            profile_key: "barrierearm",
        }
        reset_local_session_storage(storage)
        self.assertNotIn(LOCAL_RECORDS_KEY, storage)
        self.assertIn(preset_key, storage)
        self.assertIn(profile_key, storage)

    def test_next_number_uses_fixture_data(self):
        records = [record.data for record in load_records(ROOT / "data" / "fotos")]
        self.assertEqual(next_number(records, "A"), 8469)
        self.assertEqual(next_number(records, "B"), 1026)
        self.assertEqual(next_number(records, "C"), 501)

    def test_archivis_date_values(self):
        self.assertEqual(
            archivis_date_value({"jahr": 1980, "monat": 12, "tag": None}),
            "19801299",
        )
        self.assertEqual(
            archivis_date_value({"jahr": 1966, "monat": None, "tag": None}),
            "19669999",
        )
        self.assertEqual(
            archivis_date_value({"jahr": 1980, "monat": 7, "tag": None}),
            "19800799",
        )
        self.assertEqual(
            archivis_date_value({"jahr": 1980, "monat": 12, "tag": 25}),
            "19801225",
        )

    def test_fixture_records_validate(self):
        records = load_records(ROOT / "data" / "fotos")
        self.assertEqual(validate_collection(records), [])

    def test_schema_validation_is_used(self):
        errors = validate_record_schema({"id": "foto-000001"})
        self.assertTrue(any("Schemafehler" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
