"""Offline coverage of early identity reservation configuration and concurrency."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

import yaml

from backend.github.errors import RepositoryConflictError, RepositoryError
from backend.github.repository import InMemoryGitRepository
from backend.modules import load_module, ModuleConfigError
from backend.records.identity import reserve_generic_identity
from tests.test_record_runtime import write_runtime_module, write_runtime_schema


ROOT = Path(__file__).resolve().parents[1]


class EarlyReservationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.path = write_runtime_module(root, write_runtime_schema(root))
        self.config = yaml.safe_load(self.path.read_text())
        self.config['create'] = {'identity_assignment': 'reserve_before_create', 'reserve_on_start': True}
        self.path.write_text(yaml.safe_dump(self.config))
        self.module = load_module(self.path)
        self.repo = InMemoryGitRepository({'state/runtime-test.json': json.dumps({'next_record_id': 1, 'next_signature_number': {'A': 1}})})

    def tearDown(self):
        self.tmp.cleanup()

    def test_config_requires_reservation_strategy(self):
        self.assertTrue(self.module.descriptor_for_role('ehrenamtlich')['create']['reserve_on_start'])
        self.config['create']['identity_assignment'] = 'on_create'
        self.path.write_text(yaml.safe_dump(self.config))
        with self.assertRaises(ModuleConfigError):
            load_module(self.path)
        del self.config['create']['reserve_on_start']
        self.path.write_text(yaml.safe_dump(self.config))
        self.assertEqual(load_module(self.path).create_strategy['identity_assignment'], 'on_create')

    def test_parallel_commit_conflict_retries_same_operation_without_duplicate_numbers(self):
        commit = self.repo.commit_files
        other = []
        def interleave(**kwargs):
            self.repo.commit_files = commit
            other.append(reserve_generic_identity(self.repo, self.module, 'other-object', {}))
            return commit(**kwargs)
        self.repo.commit_files = interleave
        with self.assertRaises(RepositoryConflictError):
            reserve_generic_identity(self.repo, self.module, 'first-object', {})
        first = reserve_generic_identity(self.repo, self.module, 'first-object', {})
        repeated = reserve_generic_identity(self.repo, self.module, 'first-object', {})
        self.assertEqual(first, repeated)
        self.assertNotEqual(first.record_id, other[0].record_id)
        self.assertNotEqual(first.identity['signatur.anzeige'], other[0].identity['signatur.anzeige'])
        state = json.loads(self.repo.files['state/runtime-test.json'])
        self.assertEqual(state['next_record_id'], 3)
        self.assertEqual(state['next_signature_number']['A'], 3)

    def test_lost_commit_response_reuses_persisted_identity(self):
        commit = self.repo.commit_files
        def lose_response(**kwargs):
            commit(**kwargs)
            raise RepositoryError('response lost after commit')
        self.repo.commit_files = lose_response
        with self.assertRaises(RepositoryError):
            reserve_generic_identity(self.repo, self.module, 'lost-response', {})
        self.repo.commit_files = commit
        reserved = reserve_generic_identity(self.repo, self.module, 'lost-response', {})
        self.assertEqual(reserved.record_id, 'test-0001')
        self.assertEqual(len(self.repo.commits), 1)
        self.assertEqual(json.loads(self.repo.files['state/runtime-test.json'])['next_record_id'], 2)

    def test_frontend_reservation_lifecycle(self):
        node = shutil.which('node') or str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')
        if not Path(node).exists():
            self.skipTest('Node unavailable')
        result = subprocess.run([node, 'tests/early_reservation.mjs'], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
