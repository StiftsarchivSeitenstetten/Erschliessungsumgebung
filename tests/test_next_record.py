import subprocess
from pathlib import Path
import unittest
from backend.modules import get_module

class NextRecordTest(unittest.TestCase):
    def test_configuration_and_frontend(self):
        module=get_module('sammlung_thoma')
        self.assertEqual(module.create_strategy['next_record']['carry_fields'],['erschliessung.objektart','signatur.format'])
        self.assertNotIn('next_record',get_module('autographen_9_6').create_strategy)
        node=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
        result=subprocess.run([str(node),'tests/next_record.mjs'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_common_guard_and_single_new_button_are_wired(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / 'app/module/module.js').read_text()
        html = (root / 'app/module/index.html').read_text()
        self.assertNotIn('id="next-object"', html)
        self.assertIn('currentDescriptor.create?.next_record ? nextObject() : startCreate()', script)
        self.assertIn('return guardUnsavedChanges({', script)
        self.assertIn('if (!next && currentDescriptor.create?.next_record) next = {seed: nextRecordSeed(currentDescriptor, {})}', script)
        self.assertIn('entry.operation === "reservation"', script)
        self.assertIn('oldReservation.status !== "reserved"', script)
        self.assertIn('Änderungen verwerfen und weiter', html)
