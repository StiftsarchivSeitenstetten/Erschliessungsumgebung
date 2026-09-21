from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from openpyxl import Workbook

from backend.migration.autographen.migration1 import (
    IGNORED_EXPORT_COLUMNS,
    REQUIRED_COLUMNS,
    MigrationError,
    SourceRow,
    category_terms,
    normalize_legacy_value,
    parse_signature,
    record_id_for_position,
    run_dry_run,
    signature_sort_key,
    transform_date,
    transform_row,
    validate_record,
    validate_signature_selection,
    verify_source_hash,
)
from backend.modules import get_module
from backend.records.runtime import RecordRuntime


class AutographMigration1Test(unittest.TestCase):
    def setUp(self):
        self.module = get_module("autographen_9_6")

    def row(self, signature="9.6.1", **changes):
        values = {column: None for column in (*REQUIRED_COLUMNS, *IGNORED_EXPORT_COLUMNS)}
        values.update({
            "Signatur": signature,
            "Kategorie": "Brief",
            "Schreiber": "Schreiberin",
            "Empfaenger": "Empfänger",
            "Datierung": "19040223",
            "Ort": "Wien",
            "Regest": "Regest",
            "Olim": "Alt 14a",
            "ErfasstVon": "Abweichender Excel-Wert",
            "ErfasstAm": "2026-01-02 03:04:05",
        })
        values.update(changes)
        return SourceRow(source_row=2, values=values)

    def test_legacy_14_normalization_is_exact(self):
        self.assertIsNone(normalize_legacy_value(14))
        self.assertIsNone(normalize_legacy_value(" 14 "))
        self.assertEqual(normalize_legacy_value("Alt 14a"), "Alt 14a")
        self.assertEqual(normalize_legacy_value("19140114"), "19140114")

    def test_signature_sort_and_deterministic_ids(self):
        signatures = ["9.6.103", "9.6.102b", "9.6.102", "9.6.102a"]
        self.assertEqual(sorted(signatures, key=signature_sort_key), ["9.6.102", "9.6.102a", "9.6.102b", "9.6.103"])
        self.assertEqual(record_id_for_position(1, self.module), "autograph-000001")
        self.assertEqual(record_id_for_position(264, self.module), "autograph-000264")
        self.assertEqual(parse_signature("9.6.102b")[:2], (102, "b"))

    def test_category_mapping_is_explicit_and_unknown_values_fail(self):
        self.assertEqual(category_terms("Fragment"), ("unbekannt", "fragment"))
        self.assertEqual(category_terms(None), ("unbekannt", "original"))
        self.assertEqual(category_terms("14"), ("unbekannt", "original"))
        with self.assertRaisesRegex(MigrationError, "Unbekannte Kategorie"):
            category_terms("Urkunde")

    def test_participants_and_organization_exceptions(self):
        ordinary, _ = transform_row(self.row(), 1, self.module)
        self.assertEqual([item["agent"]["type"] for item in ordinary["erschliessung"]["beteiligte"]], ["person", "person"])
        self.assertEqual([item["rolle"]["id"] for item in ordinary["erschliessung"]["beteiligte"]], ["absender", "empfaenger"])
        police, _ = transform_row(self.row("9.6.102b", Empfaenger="Polizei-Ministerium"), 104, self.module)
        abbey, _ = transform_row(self.row("9.6.144", Empfaenger="Stift Seitenstetten"), 146, self.module)
        self.assertEqual(police["erschliessung"]["beteiligte"][1]["agent"]["type"], "organization")
        self.assertEqual(abbey["erschliessung"]["beteiligte"][1]["agent"]["type"], "organization")

    def test_date_patterns_hints_and_222_correction(self):
        self.assertEqual(transform_date("19040223", "9.6.1"), ({"from": {"year": 1904, "month": 2, "day": 23}}, "full_date"))
        self.assertEqual(transform_date("19040299", "9.6.1"), ({"from": {"year": 1904, "month": 2}}, "year_month"))
        self.assertEqual(transform_date("19049999", "9.6.1"), ({"from": {"year": 1904}}, "year_only"))
        self.assertEqual(transform_date("19130110 (?)", "9.6.92")[0]["hinweis"], "?")
        self.assertEqual(transform_date("18970107 (vermutlich)", "9.6.246")[0]["hinweis"], "vermutlich")
        self.assertEqual(transform_date("188803003 (?)", "9.6.222")[0], {"from": {"year": 1888, "month": 3, "day": 3}, "hinweis": "?"})

    def test_110_swap_empty_place_and_provenance(self):
        swapped, facts = transform_row(self.row("9.6.110", Datierung="Wiesbaden", Ort="19070227", GeaendertAm="2026-02-03 04:05:06"), 112, self.module)
        self.assertEqual(swapped["datierung"], {"from": {"year": 1907, "month": 2, "day": 27}})
        self.assertEqual(swapped["erschliessung"]["ort"], {"name": "Wiesbaden"})
        self.assertEqual(facts["ort"], "Wiesbaden")
        self.assertEqual(swapped["technik"]["erstellt_von"], "Maria Prüller")
        self.assertEqual(swapped["technik"]["geaendert_von"], "Maria Prüller")
        self.assertEqual(swapped["technik"]["geaendert_am"], "2026-02-03T04:05:06")

        empty, _ = transform_row(self.row(Ort="14", GeaendertAm=None), 1, self.module)
        self.assertNotIn("ort", empty["erschliessung"])
        self.assertIsNone(empty["technik"]["geaendert_am"])
        self.assertIsNone(empty["technik"]["geaendert_von"])

    def test_export_fields_and_obsolete_field_are_not_generated(self):
        record, _ = transform_row(self.row(Exportiert="Ja", ExportiertAm="2026-01-01", ExportHinweis="intern"), 1, self.module)
        serialized = json.dumps(record, ensure_ascii=False)
        for field in (*IGNORED_EXPORT_COLUMNS, "korrespondenzstueck"):
            self.assertNotIn(field, serialized)

    def test_current_production_schema_validates_a_transformed_brief(self):
        record, _ = transform_row(self.row(), 1, self.module)
        self.assertEqual(validate_record(record, RecordRuntime(self.module), "9.6.1"), [])

    def test_vocabulary_error_reports_source_and_generated_values(self):
        source = self.row(Kategorie="Visitenkarte")
        record, _ = transform_row(source, 1, self.module)
        errors = validate_record(record, RecordRuntime(self.module), "9.6.1", source.values)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["error_type"], "vocabulary")
        self.assertEqual(errors[0]["field"], "erschliessung.dokumenttyp")
        self.assertEqual(errors[0]["source_value"], "Visitenkarte")
        self.assertEqual(
            errors[0]["generated_value"],
            {"id": "visitenkarte", "vocabulary_id": "autographen_dokumenttypen"},
        )
        self.assertEqual(
            errors[0]["message"],
            "erschliessung.dokumenttyp: Unbekannte Term-ID 'visitenkarte'.",
        )

    def test_signature_selection_rejects_duplicates_missing_and_263(self):
        expected = ("9.6.1", "9.6.2")
        selected = validate_signature_selection([self.row("9.6.2"), self.row("9.6.1")], expected)
        self.assertEqual([row.signature for row in selected], list(expected))
        with self.assertRaises(MigrationError):
            validate_signature_selection([self.row("9.6.1"), self.row("9.6.1")], expected)
        with self.assertRaises(MigrationError):
            validate_signature_selection([self.row("9.6.1")], expected)
        with self.assertRaises(MigrationError):
            validate_signature_selection([self.row("9.6.1"), self.row("9.6.263")], expected)

    def test_hash_mismatch_stops_before_processing(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.xlsm"
            source.write_bytes(b"not a workbook")
            with self.assertRaisesRegex(MigrationError, "SHA-256 stimmt nicht"):
                verify_source_hash(source, "deadbeef")

    def test_small_generated_workbook_runs_without_productive_write_path(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.xlsm"
            output = Path(directory) / "output"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Autographen"
            headers = ["Ort", "Signatur", *[column for column in REQUIRED_COLUMNS if column not in {"Ort", "Signatur"}], *IGNORED_EXPORT_COLUMNS]
            sheet.append(headers)
            for signature in ("9.6.1", "9.6.2"):
                values = self.row(signature).values
                sheet.append([values.get(header) for header in headers])
            workbook.save(source)
            expected_hash = sha256(source.read_bytes()).hexdigest()
            result = run_dry_run(source, output, expected_sha256=expected_hash, required_signatures=("9.6.1", "9.6.2"))

            self.assertEqual(result["errors"], [])
            self.assertEqual(result["summary"]["generated_records"], 2)
            self.assertEqual(result["summary"]["first_record_id"], "autograph-000001")
            self.assertEqual(result["summary"]["last_record_id"], "autograph-000002")
            self.assertTrue((output / "summary.json").exists())
            self.assertTrue((output / "migration_matrix.csv").exists())
            self.assertTrue((output / "special_cases.json").exists())
            self.assertEqual(json.loads((output / "errors.json").read_text(encoding="utf-8")), [])
            self.assertEqual(len(list((output / "preview").glob("*.md"))), 2)

        source_code = Path("backend/migration/autographen/migration1.py").read_text(encoding="utf-8")
        for forbidden in ("create_generic_record", "commit_files", "GitHubDataRepository", "--apply", "requests.post", "requests.put"):
            self.assertNotIn(forbidden, source_code)


if __name__ == "__main__":
    unittest.main()
