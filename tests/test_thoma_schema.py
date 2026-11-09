"""Schema-only Thoma validation through the existing RecordRuntime validator."""

from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from backend.modules import get_module
from backend.records.runtime import RecordRuntime, RecordValidationError


SCHEMA_PATH = Path(__file__).resolve().parents[1] / 'schemas' / 'thoma.schema.json'


def draft_record():
    return {
        'schema_version': 1, 'datensatz_typ': 'thoma', 'modul': 'sammlung_thoma',
        'id': 'Thoma000001', 'sammlung': 'Sammlung Thoma', 'erfassungsstatus': 'entwurf',
        'signatur': {'format': 'A', 'nummer': 1, 'anzeige': 'Sammlung Thoma A/1'},
        'erschliessung': {
            'objektart': 'Andachtsbild', 'beschreibung': '',
            'masse': [{'massart': 'Objektmaß', 'hoehe': None, 'breite': None, 'einheit': 'mm', 'bemerkung': ''}],
        },
        'technik': {
            'erstellt_am': '2026-11-09T10:00:00Z', 'erstellt_von': 'test',
            'geaendert_am': None, 'geaendert_von': None,
        },
    }


def complete_record():
    record = draft_record()
    record['erfassungsstatus'] = 'abgeschlossen'
    record['erschliessung']['beschreibung'] = 'Andachtsbild mit Ölbergmotiv.'
    record['erschliessung']['masse'][0].update(hoehe=120.5, breite=80.25)
    return record


class ThomaSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Only the schema path is needed for validation; no Thoma registration or storage.
        module = replace(get_module('autographen_9_6'), schema_path=SCHEMA_PATH)
        cls.runtime = RecordRuntime(module)
        cls.runtime.validator.check_schema(cls.runtime.schema)

    def assert_invalid(self, record):
        with self.assertRaises(RecordValidationError):
            self.runtime.validate(record)

    def test_incomplete_draft_and_complete_record(self):
        self.runtime.validate(draft_record())
        record = draft_record()
        del record['erschliessung']['beschreibung']
        del record['erschliessung']['masse'][0]['hoehe']
        del record['erschliessung']['masse'][0]['breite']
        self.runtime.validate(record)
        self.runtime.validate(complete_record())

    def test_completion_requires_nonblank_description(self):
        for value in (None, '', ' \t\n', '\u00a0'):
            with self.subTest(value=value):
                record = complete_record()
                if value is None:
                    del record['erschliessung']['beschreibung']
                else:
                    record['erschliessung']['beschreibung'] = value
                self.assert_invalid(record)

    def test_object_measure_required_in_both_states(self):
        for factory in (draft_record, complete_record):
            for measures in ([], [{'massart': 'Objektmaß, geöffnet', 'hoehe': 2, 'breite': 3, 'einheit': 'mm'}]):
                with self.subTest(state=factory.__name__, measures=measures):
                    record = factory()
                    record['erschliessung']['masse'] = measures
                    self.assert_invalid(record)

    def test_additional_measure_completion_and_free_measure_type(self):
        for missing in ('massart', 'hoehe', 'breite', 'einheit'):
            with self.subTest(missing=missing):
                record = complete_record()
                measure = {'massart': 'Rahmenmaß, frei gewählt', 'hoehe': 1.25, 'breite': 2.5, 'einheit': 'mm'}
                del measure[missing]
                record['erschliessung']['masse'].append(measure)
                self.assert_invalid(record)
        for name in ('Rahmenmaß, frei gewählt', 'Objektmaß, geöffnet', 'Plattenmaß', 'Lichte Weite'):
            record = complete_record()
            record['erschliessung']['masse'].append({'massart': name, 'hoehe': 1.25, 'breite': 2.5, 'einheit': 'mm'})
            self.runtime.validate(record)
        for name in ('', ' \t\n'):
            record['erschliessung']['masse'][-1]['massart'] = name
            self.assert_invalid(record)

    def test_measure_values(self):
        for factory in (draft_record, complete_record):
            for field in ('hoehe', 'breite'):
                for value in (0, -1, -0.5, '12.5', '12,5', True):
                    with self.subTest(state=factory.__name__, field=field, value=value):
                        record = factory()
                        record['erschliessung']['masse'][0][field] = value
                        self.assert_invalid(record)
                record = factory()
                record['erschliessung']['masse'][0][field] = None
                if factory is draft_record:
                    self.runtime.validate(record)
                else:
                    self.assert_invalid(record)

    def test_fixed_values_and_identifiers(self):
        cases = [
            ((), 'schema_version', 2), ((), 'datensatz_typ', 'foto'),
            ((), 'modul', 'thoma'), ((), 'sammlung', 'Andere Sammlung'),
            ((), 'erfassungsstatus', 'fertig'),
            (('signatur',), 'format', 'B'), (('signatur',), 'nummer', 0),
            (('signatur',), 'nummer', 1.5), (('signatur',), 'anzeige', 'Sammlung Thoma A/0'),
            (('erschliessung',), 'objektart', 'Gemälde'),
            (('erschliessung', 'masse', 0), 'einheit', 'cm'),
        ]
        cases += [((), 'id', value) for value in ('Thoma000000', 'Thoma1', 'Thoma0000001', 'thoma000001', 'Thoma000001x')]
        for path, key, value in cases:
            with self.subTest(path=path, key=key, value=value):
                record = draft_record()
                target = record
                for part in path:
                    target = target[part]
                target[key] = value
                self.assert_invalid(record)
        record = complete_record()
        record['id'] = 'Thoma999999'
        self.runtime.validate(record)

    def test_unknown_fields_rejected_at_each_object_level(self):
        for path in ((), ('signatur',), ('erschliessung',), ('erschliessung', 'masse', 0), ('technik',)):
            with self.subTest(path=path):
                record = draft_record()
                target = record
                for part in path:
                    target = target[part]
                target['unbekannt'] = 'unerlaubt'
                self.assert_invalid(record)

    def test_defaults_are_valid_annotations_and_not_inserted_by_validation(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding='utf-8'))
        self.assertEqual(schema['properties']['erfassungsstatus']['default'], 'entwurf')
        measures = schema['properties']['erschliessung']['properties']['masse']['default']
        self.assertEqual(measures, draft_record()['erschliessung']['masse'])
        record = draft_record()
        before = deepcopy(record)
        self.runtime.validate(record)
        self.assertEqual(record, before)
        del record['erfassungsstatus']
        del record['erschliessung']['masse']
        before = deepcopy(record)
        self.assert_invalid(record)
        self.assertEqual(record, before)
