"""Descriptor transport and frontend regression coverage for generic input widgets."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

from backend.modules import load_module, ModuleConfigError
from tests.test_record_runtime import write_runtime_module, write_runtime_schema


ROOT = Path(__file__).resolve().parents[1]


class InputWidgetsTest(unittest.TestCase):
    def test_frontend_widgets(self):
        node = shutil.which('node') or str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')
        if not Path(node).exists():
            self.skipTest('Node runtime unavailable')
        result = subprocess.run([node, 'tests/input_widgets.mjs'], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_schema_defaults_and_numeric_constraints_reach_nested_descriptor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            schema_path = write_runtime_schema(root)
            path = write_runtime_module(root, schema_path)
            schema = json.loads(schema_path.read_text())
            schema['properties']['daten']['properties']['beteiligte']['default'] = [{'name': 'Initial'}]
            item = schema['properties']['daten']['properties']['beteiligte']['items']
            item['properties']['name']['default'] = ''
            item['properties']['height'] = {'type': ['number', 'null'], 'exclusiveMinimum': 0, 'default': None}
            schema_path.write_text(json.dumps(schema))
            config = yaml.safe_load(path.read_text())
            repeater = next(f for f in config['form']['sections'][0]['fields'] if f['path'] == 'daten.beteiligte')
            repeater['item_fields'] = [
                {'path': 'name', 'widget': 'text_select', 'label': 'Name', 'order': 1, 'options': [{'value': 'Vorschlag', 'label': 'Vorschlag'}]},
                {'path': 'height', 'widget': 'decimal', 'label': 'Height', 'order': 2},
            ]
            path.write_text(yaml.safe_dump(config))
            module = load_module(path)
            field = module.get_field_by_path('daten.beteiligte')
            descriptor = field.descriptor_for_role('ehrenamtlich')
            self.assertEqual(descriptor['default'], [{'name': 'Initial'}])
            self.assertEqual(descriptor['item_fields'][0]['default'], '')
            height = descriptor['item_fields'][1]
            self.assertIsNone(height['default'])
            self.assertEqual(height['exclusiveMinimum'], 0)
            self.assertTrue(height['editable'])
            self.assertNotIn('default', module.get_field_by_path('daten.name').descriptor_for_role('ehrenamtlich'))
            bad = deepcopy(config)
            bad_repeater = next(f for f in bad['form']['sections'][0]['fields'] if f['path'] == 'daten.beteiligte')
            bad_repeater['item_fields'][0]['options'][0]['value'] = 12
            path.write_text(yaml.safe_dump(bad))
            with self.assertRaises(ModuleConfigError):
                load_module(path)
