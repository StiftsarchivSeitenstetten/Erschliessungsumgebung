"""Declarative Thoma configuration; all storage and counters are synthetic."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from backend.github.repository import InMemoryGitRepository
from backend.modules import get_module, get_path_value, list_modules, set_path_value
from backend.permissions import MODULE_SAMMLUNG_THOMA
from backend.permissions.rules import validate_module
from backend.records.generic_read import parse_record_content, record_path
from backend.records.generic_write import create_generic_record, update_generic_record
from backend.records.identity import reserve_generic_identity
from backend.records.module_index import dump_index, make_index, query_index, read_module_index
from backend.records.runtime import RecordPermissionError, RecordRuntime, RecordValidationError
from tests.test_record_runtime import RuntimeUser


ROOT = Path(__file__).resolve().parents[1]
ROLES = ('ehrenamtlich', 'redaktion', 'admin')
INITIAL_MEASURE = {'massart': 'Objektmaß', 'hoehe': None, 'breite': None, 'einheit': 'mm', 'bemerkung': ''}
NEW_MEASURE = {**INITIAL_MEASURE, 'massart': ''}


def thoma_repository(module):
    return InMemoryGitRepository({
        module.storage['state']['path']: json.dumps({'next_record_id': 1, 'next_signature_number': {'A': 1}}),
        module.storage['index']['path']: dump_index(make_index(module, [])),
    })


class ThomaModuleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        list_modules.cache_clear()
        cls.module = get_module(MODULE_SAMMLUNG_THOMA)

    def setUp(self):
        self.repo = thoma_repository(self.module)
        self.runtime = RecordRuntime(self.module, self.repo)
        self.user = RuntimeUser('synthetic-user', 'ehrenamtlich')

    def editable_payload(self):
        initial = self.runtime.empty_record(self.user.role)
        payload = {'erschliessung': deepcopy(initial['erschliessung'])}
        for measure in payload['erschliessung']['masse']:
            del measure['einheit']
        return payload

    def test_registry_keys_paths_and_strategies(self):
        self.assertEqual(self.module.id, 'sammlung_thoma')
        self.assertEqual(self.module.access_key, validate_module('sammlung_thoma'))
        self.assertEqual(self.module.create_strategy['server_values']['modul'], 'sammlung_thoma')
        self.assertEqual(self.module.schema_path, ROOT / 'schemas/thoma.schema.json')
        with self.assertRaises(KeyError):
            get_module('sammlung-thoma')
        self.assertEqual(record_path(self.module, 'Thoma000001'), 'data/sammlung-thoma/Thoma000001.yaml')
        self.assertEqual(self.module.storage['state']['path'], 'state/sammlung-thoma.json')
        self.assertEqual(self.module.storage['index']['path'], 'indexes/generic/sammlung-thoma.json')
        self.assertEqual(self.module.create_strategy['identity_assignment'], 'reserve_before_create')
        self.assertTrue(self.module.create_strategy['reserve_on_start'])
        first = reserve_generic_identity(self.repo, self.module, 'object-1', {})
        self.assertEqual(first.record_id, 'Thoma000001')
        self.assertEqual(first.identity, {'id': 'Thoma000001', 'signatur.format': 'A', 'signatur.nummer': 1, 'signatur.anzeige': 'Sammlung Thoma A/1'})
        self.assertEqual(reserve_generic_identity(self.repo, self.module, 'object-1', {}), first)
        second = reserve_generic_identity(self.repo, self.module, 'object-2', {})
        self.assertEqual(second.record_id, 'Thoma000002')
        self.assertEqual(second.identity['signatur.anzeige'], 'Sammlung Thoma A/2')
        self.assertEqual(len([p for p in self.repo.files if p.startswith('data/')]), 0)

    def test_editable_initial_values_and_reserved_draft_create_update(self):
        payload = self.editable_payload()
        self.assertEqual(payload['erschliessung']['objektart'], 'Andachtsbild')
        self.assertEqual(self.runtime.empty_record(self.user.role)['erschliessung']['masse'], [INITIAL_MEASURE])
        self.assertNotIn('einheit', payload['erschliessung']['masse'][0])
        reservation = reserve_generic_identity(self.repo, self.module, 'draft', {})
        stored = create_generic_record(self.repo, self.module, payload, self.user,
            self.module.create_strategy['server_values'], operation_id='draft', reserved_identity=reservation.identity, action='draft')
        self.runtime.validate(stored.data)
        self.assertEqual(stored.data['erfassungsstatus'], 'entwurf')
        self.assertEqual(stored.data['sammlung'], 'Sammlung Thoma')
        self.assertEqual(stored.data['signatur']['format'], 'A')
        self.assertEqual(stored.data['technik']['erstellt_von'], self.user.username)
        self.assertFalse(self.repo.files[stored.path].startswith('---'))
        self.assertEqual(parse_record_content(self.repo.files[stored.path]), stored.data)
        payload['erschliessung']['motiv'] = 'Ölberg'
        updated = update_generic_record(self.repo, self.module, stored.record_id, payload, stored.revision, self.user, action='draft')
        self.assertEqual(updated.data['erschliessung']['motiv'], 'Ölberg')
        self.assertEqual(updated.data['signatur'], stored.data['signatur'])
        self.assertEqual(updated.data['technik']['erstellt_am'], stored.data['technik']['erstellt_am'])
        self.assertEqual(updated.data['technik']['geaendert_von'], self.user.username)

    def test_protected_fields_rejected_for_every_role(self):
        protected = {
            'id': 'Thoma000099', 'sammlung': 'Andere Sammlung',
            'signatur.format': 'B', 'signatur.nummer': 99, 'signatur.anzeige': 'Sammlung Thoma A/99',
            'erfassungsstatus': 'abgeschlossen', 'schema_version': 2, 'modul': 'other',
            'datensatz_typ': 'other', 'technik.erstellt_am': 'forged', 'technik.erstellt_von': 'forged',
            'technik.geaendert_am': 'forged', 'technik.geaendert_von': 'forged',
        }
        reservation = reserve_generic_identity(self.repo, self.module, 'protected', {})
        values = {**self.module.create_strategy['server_values'], **reservation.identity, 'datensatz_typ': 'thoma'}
        existing = self.runtime.prepare_create(self.editable_payload(), self.user, values, action='draft')
        for role in ROLES:
            user = RuntimeUser('synthetic-user', role)
            descriptor = self.module.descriptor_for_role(role)
            for path in ('id', 'sammlung', 'signatur.format', 'signatur.anzeige', 'erfassungsstatus'):
                field = next(f for f in descriptor['fields'] if f['path'] == path)
                self.assertTrue(field['visible'])
                self.assertFalse(field['editable'])
            for path, value in protected.items():
                with self.subTest(role=role, path=path):
                    forged = {}
                    set_path_value(forged, path, value)
                    with self.assertRaises(RecordPermissionError):
                        self.runtime.prepare_create(forged, user, values)
                    with self.assertRaises(RecordPermissionError):
                        self.runtime.prepare_update(existing, forged, user)
        forged = deepcopy(existing)
        forged['erschliessung']['masse'][0]['einheit'] = 'cm'
        with self.assertRaises(RecordValidationError):
            self.runtime.validate(forged)

    def test_form_order_options_and_search(self):
        self.assertEqual([s.id for s in self.module.sections], ['identifikation', 'beschreibung', 'abmessungen'])
        self.assertTrue(all(not f.help for f in self.module.fields))
        measures = self.module.get_field_by_path('erschliessung.masse').descriptor_for_role(self.user.role)
        items = {f['path']: f for f in measures['item_fields']}
        self.assertEqual(items['massart']['widget'], 'text_select')
        self.assertEqual([o['value'] for o in items['massart']['options']], ['Objektmaß', 'Objektmaß, geöffnet', 'Plattenmaß', 'Lichte Weite'])
        self.assertEqual(items['hoehe']['widget'], 'decimal')
        self.assertEqual(items['breite']['exclusiveMinimum'], 0)
        descriptor = self.module.descriptor_for_role(self.user.role)
        self.assertEqual(descriptor['search']['lookup'], ['id', 'signatur.anzeige'])
        self.assertEqual([c['path'] for c in descriptor['list']['columns']], ['id', 'signatur.anzeige', 'erschliessung.motiv', 'erfassungsstatus'])
        payload = self.editable_payload()
        payload['erschliessung']['motiv'] = 'Ölberg'
        reservation = reserve_generic_identity(self.repo, self.module, 'search', {})
        stored = create_generic_record(self.repo, self.module, payload, self.user, self.module.create_strategy['server_values'], operation_id='search', reserved_identity=reservation.identity, action='draft')
        index = read_module_index(self.repo, self.module)
        for path, value in [('id', stored.record_id), ('signatur.anzeige', 'Sammlung Thoma A/1')]:
            matches = query_index(self.module, index, self.user.role, lookup_field=path, lookup_value=value)
            self.assertEqual([m['record_id'] for m in matches], [stored.record_id])
            self.assertEqual(matches[0]['values']['erfassungsstatus'], 'entwurf')
        self.assertEqual(len(query_index(self.module, index, self.user.role, q='Ölberg')), 1)

    def test_readonly_initial_values_are_available_before_create(self):
        initial = self.runtime.empty_record(self.user.role)
        self.assertEqual(initial.get('sammlung'), 'Sammlung Thoma')
        self.assertEqual(initial.get('erfassungsstatus'), 'entwurf')
        self.assertEqual(get_path_value(initial, 'signatur.format'), 'A')

    def test_repeater_unit_is_readonly(self):
        field = self.module.get_field_by_path('erschliessung.masse').descriptor_for_role(self.user.role)
        unit = next(f for f in field['item_fields'] if f['path'] == 'einheit')
        self.assertFalse(unit['editable'])

    def test_frontend_defaults_and_existing_data(self):
        node = shutil.which('node') or str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')
        if not Path(node).exists():
            self.skipTest('Node unavailable')
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'thoma-descriptor.json'
            fixture.write_text(json.dumps({'descriptor': self.module.descriptor_for_role(self.user.role), 'record': self.runtime.empty_record(self.user.role)}))
            result = subprocess.run([node, 'tests/thoma_form.mjs', str(fixture)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(next(line.removeprefix('THOMA_PAYLOAD:') for line in result.stdout.splitlines() if line.startswith('THOMA_PAYLOAD:')))
            reservation = reserve_generic_identity(self.repo, self.module, 'frontend', {})
            stored = create_generic_record(self.repo, self.module, payload, self.user,
                self.module.create_strategy['server_values'], operation_id='frontend', reserved_identity=reservation.identity, action='draft')
            self.assertTrue(all(m['einheit'] == 'mm' for m in stored.data['erschliessung']['masse']))
            self.assertEqual(len(stored.data['erschliessung']['masse']), 3)
            forged = deepcopy(payload)
            forged['erschliessung']['masse'][0]['einheit'] = 'mm'
            with self.assertRaises(RecordPermissionError):
                self.runtime.filter_for_edit(forged, self.user.role)

    def test_inventory_and_storage_sequences_are_independent(self):
        self.repo.files[self.module.storage['state']['path']] = json.dumps({'next_record_id': 10, 'next_signature_number': {'A': 7}})
        reserved = reserve_generic_identity(self.repo, self.module, 'independent-counters', {})
        self.assertEqual(reserved.record_id, 'Thoma000010')
        self.assertEqual(reserved.identity['signatur.anzeige'], 'Sammlung Thoma A/7')
