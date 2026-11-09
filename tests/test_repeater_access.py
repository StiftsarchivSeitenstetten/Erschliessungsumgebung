"""Generic rights, readonly defaults and recursive repeater write boundaries."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from backend.modules import load_module
from backend.modules.registry import RepeaterConfigError, load_modules
from backend.records.runtime import RecordRuntime, RecordPermissionError
from backend.records.module_index import build_index_entry, make_index, query_index
from backend.records.generic_read import list_values_for_role
from tests.test_record_runtime import RuntimeUser

ROOT = Path(__file__).resolve().parents[1]
ALL = ['ehrenamtlich', 'redaktion', 'admin']


def make_fixture(directory):
    leaf = {'type': 'object', 'additionalProperties': False,
        'required': ['text', 'locked', 'hidden'], 'properties': {
            'text': {'type': 'string', 'default': ''},
            'locked': {'type': 'string', 'default': 'nested fixed', 'const': 'nested fixed'},
            'hidden': {'type': 'string', 'default': 'nested secret', 'const': 'nested secret'},
        }}
    row = {'type': 'object', 'additionalProperties': False,
        'required': ['text', 'locked', 'hidden', 'nested'], 'properties': {
            'text': {'type': 'string', 'default': ''},
            'locked': {'type': 'string', 'default': 'fixed', 'const': 'fixed'},
            'hidden': {'type': 'string', 'default': 'secret', 'const': 'secret'},
            'nested': {'type': 'array', 'items': leaf, 'default': []},
        }}
    default = {'text': 'Initial', 'locked': 'fixed', 'hidden': 'secret',
        'nested': [{'text': 'Nested', 'locked': 'nested fixed', 'hidden': 'nested secret'}]}
    schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema',
        'type': 'object', 'additionalProperties': False,
        'properties': {
            'id': {'type': 'string', 'default': 'NEVER INVENT THIS ID'},
            'signatur': {'type': 'object', 'properties': {'anzeige': {'type': 'string', 'default': 'NEVER INVENT THIS SIGNATURE'}}},
            'readonly': {'type': 'string', 'default': 'initial fixed'},
            'hidden': {'type': 'string', 'default': 'initial secret'},
            'rows': {'type': 'array', 'items': row, 'default': [default]},
            'technik': json.loads((ROOT / 'schemas/thoma.schema.json').read_text())['properties']['technik'],
        }}
    schema_path = directory / 'schema.json'
    schema_path.write_text(json.dumps(schema))
    def field(path, widget='text', children=None):
        data = {'path': path, 'widget': widget, 'label': path, 'order': 1}
        if children is not None: data['item_fields'] = children
        return data
    fields = [field('id'), field('signatur.anzeige'), field('readonly'), field('hidden'),
        field('rows', 'repeater', [field('text'), field('locked'), field('hidden'),
            field('nested', 'repeater', [field('text'), field('locked'), field('hidden')])])]
    config = {'config_version': 1,
        'module': {'id': 'restricted_fixture', 'access_key': 'restricted_fixture', 'label': 'Fixture', 'record_type': 'fixture'},
        'schema': {'path': str(schema_path)},
        'storage': {'data_dir': 'data/synthetic', 'filename': {'strategy': 'record_id_with_extension', 'extension': '.yaml'}},
        'id': {'strategy': 'prefixed_sequence', 'prefix': 'fixture-', 'width': 4},
        'signature': {'strategy': 'partitioned_sequence', 'partitions': ['A'], 'pattern': 'Fixture {nummer}'},
        'search': {'fulltext': []}, 'list': {'columns': [{'path': 'id', 'label': 'ID'}]}, 'presets': {'enabled_fields': [], 'disabled_fields': []},
        'create': {'identity_assignment': 'on_create', 'server_values': {'readonly': 'server fixed', 'hidden': 'server secret'}},
        'form': {'sections': [{'id': 'main', 'label': 'Fixture', 'order': 1, 'fields': fields}]},
        'access': {'fields': {
            'id': {'view': ALL, 'edit': []}, 'signatur.anzeige': {'view': ALL, 'edit': []},
            'readonly': {'view': ALL, 'edit': []}, 'hidden': {'view': ['redaktion'], 'edit': ['redaktion']},
            'rows': {'view': ALL, 'edit': ALL},
            'rows[].locked': {'view': ALL, 'edit': ['redaktion']},
            'rows[].hidden': {'view': ['redaktion'], 'edit': ['redaktion']},
            'rows[].nested': {'view': ALL, 'edit': ALL},
            'rows[].nested[].text': {'view': ALL, 'edit': ALL},
            'rows[].nested[].locked': {'view': ALL, 'edit': []},
            'rows[].nested[].hidden': {'view': ['redaktion'], 'edit': ['redaktion']},
        }}}
    path = directory / 'module.yaml'
    path.write_text(json.dumps(config))
    return load_module(path), config, path


class RepeaterAccessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.module, self.config, self.path = make_fixture(Path(self.tmp.name))
        self.runtime = RecordRuntime(self.module)
        self.user = RuntimeUser('test', 'ehrenamtlich')

    def tearDown(self): self.tmp.cleanup()

    def test_initial_visibility_defaults_and_no_unreserved_identity(self):
        initial = self.runtime.empty_record(self.user.role)
        self.assertEqual(initial['readonly'], 'server fixed')
        self.assertNotIn('hidden', initial)
        self.assertNotIn('id', initial)
        self.assertNotIn('signatur', initial)
        self.assertEqual(initial['rows'][0]['locked'], 'fixed')
        self.assertNotIn('hidden', initial['rows'][0])
        self.assertNotIn('hidden', initial['rows'][0]['nested'][0])
        descriptor = self.module.descriptor_for_role(self.user.role)
        rows = next(f for f in descriptor['fields'] if f['path'] == 'rows')
        self.assertNotIn('hidden', rows['default'][0])
        self.assertNotIn('hidden', rows['default'][0]['nested'][0])
        self.assertNotIn('hidden', descriptor['create']['server_values'])
        self.assertEqual(self.runtime.empty_record('redaktion')['hidden'], 'initial secret')  # Editable field: existing schema-default convention.

    def test_inheritance_and_parent_limits(self):
        rows = self.module.get_field_by_path('rows')
        text, locked, hidden, nested = rows.item_fields
        self.assertEqual(text.view_roles, rows.view_roles)
        self.assertEqual(text.edit_roles, rows.edit_roles)
        self.assertFalse(locked.can_edit('ehrenamtlich'))
        self.assertTrue(locked.can_edit('redaktion'))
        self.assertFalse(hidden.can_view('ehrenamtlich'))
        self.assertTrue(nested.can_edit('admin'))
        self.assertTrue(nested.item_fields[0].can_edit('admin'))
        self.config['access']['fields']['rows'] = {'view': ['ehrenamtlich'], 'edit': []}
        self.path.write_text(json.dumps(self.config))
        limited = load_module(self.path).get_field_by_path('rows')
        self.assertFalse(limited.item_fields[1].can_view('redaktion'))
        self.assertFalse(limited.item_fields[1].can_edit('redaktion'))
        self.assertFalse(limited.item_fields[3].item_fields[0].can_edit('ehrenamtlich'))

    def test_rejects_protected_values_at_every_depth(self):
        for payload in ({'readonly': 'forged'}, {'hidden': 'forged'},
            {'rows': [{'locked': 'fixed'}]}, {'rows': [{'hidden': 'forged'}]},
            {'rows': [{'nested': [{'locked': 'nested fixed'}]}]},
            {'rows': [{'nested': [{'hidden': 'forged'}]}]}):
            with self.subTest(payload=payload), self.assertRaises(RecordPermissionError):
                self.runtime.filter_for_edit(payload, self.user.role)

    def test_new_items_get_constants_and_divergent_history_is_rejected(self):
        payload = {'rows': [{'text': 'New', 'nested': [{'text': 'Deep new'}]}]}
        original = deepcopy(payload)
        created = self.runtime.prepare_create(payload, self.user, {'id': 'fixture-1', 'readonly': 'server fixed'})
        self.assertEqual(payload, original)
        self.assertEqual(created['rows'][0]['locked'], 'fixed')
        self.assertEqual(created['rows'][0]['hidden'], 'secret')
        self.assertEqual(created['rows'][0]['nested'][0]['locked'], 'nested fixed')
        updated = self.runtime.prepare_update(created, {'rows': [
            {'text': 'Changed', 'nested': [{'text': 'Changed nested'}]},
            {'text': 'Added', 'nested': [{'text': 'Added nested'}]},
        ]}, self.user)
        self.assertEqual(updated['rows'][0]['locked'], 'fixed')
        self.assertEqual(updated['rows'][1]['nested'][0]['locked'], 'nested fixed')
        visible = self.runtime.filter_for_view(updated, self.user.role)
        self.assertNotIn('hidden', visible['rows'][0])
        self.assertNotIn('hidden', visible['rows'][1]['nested'][0])
        created['rows'][0]['locked'] = 'Historic protected value'
        with self.assertRaisesRegex(RecordPermissionError, 'rows.0.locked'):
            self.runtime.prepare_update(created, {'rows': []}, self.user)

    def test_list_and_index_do_not_reveal_hidden_item_values(self):
        module = replace(self.module,
            search_config={'fulltext': ['rows', 'rows.nested', 'rows.hidden']},
            list_config={'columns': [{'path': 'rows', 'label': 'Rows'}, {'path': 'rows.hidden', 'label': 'Hidden'}]})
        runtime = RecordRuntime(module)
        record = runtime.prepare_create({'rows': [{'text': 'Public', 'nested': [{'text': 'Nested public'}]}]}, self.user, {'id': 'fixture-1'})
        index = make_index(module, [build_index_entry(module, record, 'revision')])
        visible = query_index(module, index, self.user.role)
        self.assertNotIn('rows.hidden', visible[0]['values'])
        self.assertNotIn('hidden', visible[0]['values']['rows'][0])
        self.assertNotIn('hidden', visible[0]['values']['rows'][0]['nested'][0])
        self.assertEqual(query_index(module, index, self.user.role, q='secret'), [])
        self.assertEqual(len(query_index(module, index, 'redaktion', q='secret')), 1)
        values = list_values_for_role(record, module, self.user.role)
        self.assertNotIn('hidden', values['rows'][0])

    def alter_schema(self, alter):
        schema_path = Path(self.tmp.name) / 'schema.json'
        schema = json.loads(schema_path.read_text())
        alter(schema['properties']['rows']['items'])
        schema_path.write_text(json.dumps(schema))

    def test_default_without_const_and_variable_nested_fields_rejected(self):
        for path in ('locked', 'nested'):
            with self.subTest(path=path):
                self.module, self.config, self.path = make_fixture(Path(self.tmp.name))
                def alter(row):
                    node = row if path == 'locked' else row['properties']['nested']['items']
                    del node['properties']['locked']['const']
                self.alter_schema(alter)
                with self.assertRaisesRegex(RepeaterConfigError, 'locked.*Schema-const'):
                    load_module(self.path)

    def test_optional_const_is_not_sufficient(self):
        self.alter_schema(lambda row: row['required'].remove('locked'))
        with self.assertRaisesRegex(RepeaterConfigError, 'rows.*locked'):
            load_module(self.path)

    def test_schema_only_variable_field_and_ambiguous_structure_rejected(self):
        self.alter_schema(lambda row: row['properties'].update(legacy={'type': 'string'}))
        with self.assertRaisesRegex(RepeaterConfigError, 'legacy'):
            load_module(self.path)
        self.module, self.config, self.path = make_fixture(Path(self.tmp.name))
        self.alter_schema(lambda row: row.update(anyOf=[{'required': ['text']}, {}]))
        with self.assertRaisesRegex(RepeaterConfigError, 'Struktur'):
            load_module(self.path)

    def test_unsafe_module_does_not_disable_other_modules(self):
        self.alter_schema(lambda row: row['properties']['locked'].pop('const'))
        valid = ROOT / 'ui/modules/sammlung-thoma.yaml'
        with self.assertLogs('backend.modules.registry', 'ERROR') as logs:
            modules = load_modules([self.path, valid])
        self.assertEqual([m.id for m in modules], ['sammlung_thoma'])
        self.assertIn('rows[].locked', logs.output[0])

    def test_schema_only_constant_is_hidden_and_rebuilt(self):
        def alter(row):
            row['properties']['canonical_secret'] = {'const': 'never expose'}
            row['required'].append('canonical_secret')
            row['default'] = {'canonical_secret': 'never expose'}
        self.alter_schema(alter)
        runtime = RecordRuntime(load_module(self.path))
        record = runtime.prepare_create({'rows': [{'text': 'one', 'nested': []}]}, self.user)
        self.assertEqual(record['rows'][0]['canonical_secret'], 'never expose')
        self.assertNotIn('canonical_secret', runtime.filter_for_view(record, self.user.role)['rows'][0])
        self.assertNotIn('never expose', json.dumps(runtime.module.descriptor_for_role(self.user.role)))

    def test_unknown_history_and_divergent_nested_constants_rejected_even_on_delete(self):
        record = self.runtime.prepare_create({'rows': [{'text': 'one', 'nested': [{'text': 'deep'}]}]}, self.user)
        for field, value in [('legacy', 'unique historical value'), ('hidden', 'different secret')]:
            changed = deepcopy(record)
            changed['rows'][0][field] = value
            with self.subTest(field=field), self.assertRaises(RecordPermissionError):
                self.runtime.prepare_update(changed, {'rows': []}, self.user)
        record['rows'][0]['nested'][0]['locked'] = 'unique nested value'
        with self.assertRaisesRegex(RecordPermissionError, 'nested.0.locked'):
            self.runtime.prepare_update(record, {'rows': []}, self.user)

    def test_actual_autograph_and_photo_repeaters_replace_entire_lists(self):
        examples = [
            ('autographen.yaml', 'erschliessung.beteiligte',
                {'agent': {'type': 'person', 'name': 'Second', 'hinweis': 'retained structured value'}}),
            ('papierabzuege.yaml', 'erschliessung.dargestellte_personen', {'name': 'Second'}),
        ]
        for filename, path, incoming in examples:
            with self.subTest(module=filename):
                runtime = RecordRuntime(load_module(ROOT / 'ui/modules' / filename))
                field = runtime.module.get_field_by_path(path)
                self.assertEqual(field.repeater_policies['redaktion'], 'replace')
                existing = [{'name': 'First', 'hinweis': 'old'}, {'name': 'Second', 'hinweis': 'remove'}]
                merged = runtime._merge_repeater(field, [incoming], existing, runtime._schema_for_path(path), 'redaktion')
                self.assertEqual(merged, [incoming])
                self.assertIsNot(merged[0], incoming)

    def test_frontend_rights_payload_and_recovery(self):
        node = shutil.which('node') or str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')
        if not Path(node).exists(): self.skipTest('Node unavailable')
        fixture = Path(self.tmp.name) / 'descriptor.json'
        fixture.write_text(json.dumps({'descriptor': self.module.descriptor_for_role(self.user.role), 'record': self.runtime.empty_record(self.user.role)}))
        result = subprocess.run([node, 'tests/repeater_access.mjs', str(fixture)], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
