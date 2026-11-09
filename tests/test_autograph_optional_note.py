"""Autograph optional internal note through canonical create/update persistence."""
import unittest
from backend.modules import get_module
from backend.records.runtime import RecordRuntime, RecordValidationError
from backend.records.generic_write import create_generic_record, update_generic_record
from tests.test_thoma_module import thoma_repository
from tests.test_record_runtime import RuntimeUser


class AutographOptionalNoteTest(unittest.TestCase):
    def test_missing_empty_existing_and_cleared_note(self):
        module = get_module('autographen_9_6')
        repo = thoma_repository(module)
        user = RuntimeUser('synthetic', 'redaktion')
        payload = {'erschliessung': {'dokumenttyp': {'id': 'brief'}, 'erhaltungsform': {'id': 'original'}, 'beteiligte': []}}
        runtime = RecordRuntime(module, repo)
        self.assertFalse(module.get_field_by_path('erschliessung.interne_bemerkung').required)
        stored = create_generic_record(repo, module, payload, user, module.create_strategy['server_values'], operation_id='optional-note')
        self.assertNotIn('interne_bemerkung', stored.data['erschliessung'])
        for value in ('', 'Vorhandene Bemerkung', ''):
            stored = update_generic_record(repo, module, stored.record_id,
                {'erschliessung': {**stored.data['erschliessung'], 'interne_bemerkung': value}}, stored.revision, user)
            self.assertEqual(stored.data['erschliessung']['interne_bemerkung'], value)
        for field in ('dokumenttyp', 'erhaltungsform', 'beteiligte'):
            invalid = dict(stored.data)
            invalid['erschliessung'] = dict(stored.data['erschliessung'])
            del invalid['erschliessung'][field]
            with self.subTest(field=field), self.assertRaises(RecordValidationError):
                runtime.validate(invalid)
