from copy import deepcopy
import unittest
from backend.modules import get_module
from backend.records.runtime import RecordRuntime, RecordValidationError, RecordPermissionError
from backend.records.identity import reserve_generic_identity
from backend.records.generic_write import create_generic_record, update_generic_record
from backend.records.module_index import read_module_index
from backend.github.errors import RepositoryConflictError
from tests.test_record_runtime import RuntimeUser
from tests.test_thoma_module import thoma_repository

class RecordActionsTest(unittest.TestCase):
    def setUp(self):
        self.module = get_module('sammlung_thoma')
        self.repo = thoma_repository(self.module)
        self.user = RuntimeUser('test', 'ehrenamtlich')
        self.payload = {'erschliessung': {'objektart':'Andachtsbild', 'beschreibung':'', 'masse':[
            {'massart':'Objektmaß', 'hoehe':None, 'breite':None, 'bemerkung':''}]}}
        self.identity = reserve_generic_identity(self.repo,self.module,'op',{}).identity
    def create(self, action):
        return create_generic_record(self.repo,self.module,self.payload,self.user,self.module.create_strategy['server_values'],operation_id='op',reserved_identity=self.identity,action=action)
    def fill(self):
        self.payload['erschliessung']['beschreibung']='Andachtsbild'
        self.payload['erschliessung']['masse'][0].update(hoehe=12.5,breite=9.5)
    def test_draft_complete_correction_and_conflict(self):
        stored=self.create('draft')
        self.assertEqual(stored.data['erfassungsstatus'],'entwurf')
        before=deepcopy(self.repo.files)
        with self.assertRaises(RecordValidationError):
            update_generic_record(self.repo,self.module,stored.record_id,self.payload,stored.revision,self.user,action='complete')
        self.assertEqual(before,self.repo.files)
        self.fill()
        complete=update_generic_record(self.repo,self.module,stored.record_id,self.payload,stored.revision,self.user,action='complete')
        self.assertEqual(complete.data['erfassungsstatus'],'abgeschlossen')
        self.payload['erschliessung']['beschreibung']='Korrektur'
        corrected=update_generic_record(self.repo,self.module,stored.record_id,self.payload,complete.revision,self.user,action='save')
        self.assertEqual(corrected.data['id'],stored.record_id)
        self.assertEqual(corrected.data['signatur'],stored.data['signatur'])
        self.assertEqual(read_module_index(self.repo,self.module)['records'][0]['values']['erfassungsstatus'],'abgeschlossen')
        for action in ('draft','complete',None):
            with self.assertRaises(RecordValidationError):
                update_generic_record(self.repo,self.module,stored.record_id,self.payload,corrected.revision,self.user,action=action)
        with self.assertRaises(RepositoryConflictError):
            update_generic_record(self.repo,self.module,stored.record_id,self.payload,stored.revision,self.user,action='save')
    def test_direct_complete_retry_and_additional_incomplete_measure(self):
        self.fill()
        self.payload['erschliessung']['masse'].append({'massart':'Plattenmaß','hoehe':None,'breite':None})
        with self.assertRaises(RecordValidationError): self.create('complete')
        self.payload['erschliessung']['masse'].pop()
        result=self.create('complete')
        count=len(self.repo.commits)
        self.assertEqual(self.create('complete').record_id,result.record_id)
        self.assertEqual(len(self.repo.commits),count)
        self.assertEqual(result.data['erfassungsstatus'],'abgeschlossen')
    def test_invalid_numbers_and_manipulated_status(self):
        for value in (0,-1,'12,5','bad'):
            self.payload['erschliessung']['masse'][0]['hoehe']=value
            with self.assertRaises(RecordValidationError): self.create('draft')
        self.payload['erfassungsstatus']='abgeschlossen'
        with self.assertRaises(RecordPermissionError): self.create('draft')

    def test_frontend_action_queue(self):
        import subprocess
        from pathlib import Path
        node = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
        result = subprocess.run([str(node), 'tests/action_queue.mjs'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
