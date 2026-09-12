from pathlib import Path
import tempfile
import unittest

from backend.records.photo_index import (
    PhotoIndex,
    build_photo_index,
    build_photo_index_from_directory,
    dump_photo_index,
    validate_photo_index,
)
from scripts.foto_core import build_signature, render_photo_markdown


def record(record_id: str, format_code: str, number: int, suffix: str | None = None) -> dict:
    signatur = build_signature(format_code, number)
    if suffix:
        signatur["zusatz"] = suffix
        signatur["anzeige"] = f"{signatur['anzeige']}{suffix}"
    return {
        "schema_version": 1,
        "id": record_id,
        "datensatz_typ": "foto",
        "modul": "papierabzuege_9_4_2",
        "signatur": signatur,
        "erschliessung": {
            "titel": None,
            "beschriftung": f"Beschriftung {record_id}",
            "beschreibung": None,
            "dargestellte_personen": [],
            "herkunft": None,
            "sammler": None,
            "fotograf": None,
            "rechteinhaber": None,
            "orte": [],
            "schlagworte": [],
            "altsignaturen": [],
            "interne_bemerkung": None,
        },
        "korrespondenzstueck": None,
        "datierung": {"jahr": None, "monat": None, "tag": None},
        "redaktion": {"stufe": "ehrenamtlich"},
        "bearbeitung": {"status": "in_bearbeitung"},
        "publikation": {"status": "intern"},
        "technik": {"quelle": "migration_excel"},
    }


class PhotoIndexTest(unittest.TestCase):
    def test_build_index_from_10330_records(self):
        records = [
            record(f"foto-{index:06d}", "A", index)
            for index in range(1, 10331)
        ]
        index = build_photo_index(records)
        self.assertEqual(index["schema_version"], 1)
        self.assertEqual(len(index["records"]), 10330)
        self.assertEqual(len({entry["id"] for entry in index["records"]}), 10330)
        self.assertEqual(len({entry["signatur"] for entry in index["records"]}), 10330)

    def test_suffixed_signatures_and_signature_family(self):
        index = PhotoIndex(build_photo_index([
            record("foto-000001", "A", 5528, "a"),
            record("foto-000002", "A", 5528, "b"),
            record("foto-000003", "B", 1),
        ])["records"])
        self.assertEqual(index.by_signature("9.4.2.A.5528a")["id"], "foto-000001")
        self.assertEqual(
            [entry["id"] for entry in index.signature_family("9.4.2.A.5528")],
            ["foto-000001", "foto-000002"],
        )

    def test_adjacent_ids_use_existing_index_entries_not_numeric_counting(self):
        index = PhotoIndex(build_photo_index([
            record("foto-000001", "A", 1),
            record("foto-008116", "A", 8116),
            record("foto-008118", "A", 8118),
            record("foto-010330", "A", 10330, "a"),
            record("foto-010331", "A", 10330, "b"),
        ])["records"])
        self.assertEqual(index.adjacent_ids("foto-000001"), {"previous": None, "next": "foto-008116"})
        self.assertEqual(index.adjacent_ids("foto-008116"), {"previous": "foto-000001", "next": "foto-008118"})
        self.assertEqual(index.adjacent_ids("foto-008118"), {"previous": "foto-008116", "next": "foto-010330"})
        self.assertEqual(index.adjacent_ids("foto-010331"), {"previous": "foto-010330", "next": None})
        self.assertEqual(index.adjacent_ids("foto-008117"), {"previous": None, "next": None})

    def test_build_from_directory_validates_files_and_excludes_deferred_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data" / "fotos"
            data_dir.mkdir(parents=True)
            (data_dir / "foto-000001.md").write_text(render_photo_markdown(record("foto-000001", "A", 1)), encoding="utf-8")
            (data_dir / "foto-000002.md").write_text(render_photo_markdown(record("foto-000002", "A", 1, "a")), encoding="utf-8")
            index = build_photo_index_from_directory(data_dir)
            self.assertEqual(validate_photo_index(data_dir, index), [])
            self.assertNotIn("foto-008117", {entry["id"] for entry in index["records"]})
            self.assertIn('"zusatz": "a"', dump_photo_index(index))

    def test_validation_rejects_missing_file_duplicate_signature_and_deferred_conflict(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / "foto-000001.md").write_text(render_photo_markdown(record("foto-000001", "A", 1)), encoding="utf-8")
            index = {
                "schema_version": 1,
                "records": [
                    {"id": "foto-000001", "signatur": "9.4.2.A.1", "format": "A", "nummer": 1, "zusatz": None},
                    {"id": "foto-000002", "signatur": "9.4.2.A.1", "format": "A", "nummer": 1, "zusatz": None},
                    {"id": "foto-008117", "signatur": "9.4.2.A.99", "format": "A", "nummer": 99, "zusatz": None},
                ],
            }
            errors = validate_photo_index(data_dir, index)
            self.assertTrue(any("Doppelte Signatur" in error for error in errors))
            self.assertTrue(any("Indexeintrag ohne Datei: foto-000002" in error for error in errors))
            self.assertTrue(any("foto-008117" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
