from pathlib import Path
import unittest

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from foto_core import (  # noqa: E402
    archivis_date_value,
    build_signature,
    load_records,
    next_number,
    validate_collection,
)


class FotoCoreTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
