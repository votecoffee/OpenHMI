from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from examples.build_bench import BenchSpec, build
from openhmi.workspace import ProjectWorkspace
from tests.test_logix_history import FakePLC


def bench_input():
    return {
        'route': 'offline-only/0',
        'overview_update_ms': 1000,
        'comparison_update_ms': 200,
        'comparison_tags': ['BenchRun'],
        'tags': [
            {'name': 'BenchRun', 'address': 'Motor.Running', 'type': 'boolean'},
            {'name': 'BenchLevel', 'address': 'Level', 'type': 'number'},
            {'name': 'BenchIndexed', 'address': 'TestArray[1]', 'type': 'integer'},
        ],
    }


class BenchBuilderTests(unittest.TestCase):
    def test_held_project_and_imported_backup_use_only_approved_read_bindings(self):
        class BenchPLC(FakePLC):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.values['TestArray[1]'] = 15

        with ExitStack() as stack:
            root = stack.enter_context(TemporaryDirectory())
            output = Path(root) / 'bench'
            with patch('pycomm3.LogixDriver', side_effect=AssertionError('Generator opened a PLC')):
                database = build(BenchSpec.model_validate(bench_input()), output)
            self.assertTrue(database.with_suffix('.hold').is_file())
            workspace = ProjectWorkspace(database)
            stack.callback(workspace.current.state.store.close)
            driver = workspace.current.state.driver
            self.assertTrue(driver.plc_hold)
            self.assertEqual(driver.connections, {})
            driver.factory = BenchPLC
            stack.callback(driver.close)
            client = TestClient(workspace.current)
            state = client.get('/api/project').json()
            active = state['active']
            self.assertEqual(active['commands'], [])
            self.assertEqual(active['recipe_transfers'], [])
            self.assertFalse(active['identity_publication']['enabled'])
            self.assertEqual(active['historian']['tags'], [])
            self.assertEqual(active['alarms'], [])
            self.assertTrue(all(not item['writable'] for item in active['tags']))
            self.assertEqual({item['kind'] for item in active['controls']}, {'indicator', 'numeric'})

            workspace.import_backup('Restored', (output / 'OpenHMI-Bench-backup.zip').read_bytes())
            restored = workspace._app(output / 'Restored.openhmi.sqlite3')
            try:
                self.assertTrue(restored.state.driver.plc_hold)
                self.assertEqual(restored.state.store.snapshot()['active'], active)
            finally:
                restored.state.store.close()

            response = client.post('/api/project/apply', json={'expected_revision': state['draft_revision']})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertFalse(database.with_suffix('.hold').exists())
            driver.lease('overview-viewer', ['overview'], 1)
            driver.poll(1)
            plc = driver.connections['bench'].client
            self.assertEqual(set(plc.reads[-1]), {'Motor.Running', 'Level', 'TestArray[1]'})
            driver.lease('comparison-viewer', ['comparison'], 2)
            driver.poll(2)
            self.assertEqual(driver.status()[0]['groups'], [
                {'rate_ms': 200, 'addresses': ['Motor.Running']},
                {'rate_ms': 1000, 'addresses': ['Level', 'TestArray[1]']},
            ])
            self.assertEqual(driver.sample_snapshot(2)['BenchIndexed']['value'], 15)
            with self.assertRaisesRegex(ValueError, 'read-only'):
                driver.write('BenchRun', [False])
            self.assertEqual(plc.writes, [])

    def test_rejects_unapproved_options_and_refuses_existing_output(self):
        for field, value in [('writable', True), ('address', 'TestArray[1]{10}'),
                             ('address', 'Program:Bench.Tag'), ('type', 'struct')]:
            config = bench_input()
            config['tags'][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                BenchSpec.model_validate(config)
        config = bench_input()
        config['comparison_tags'] = ['Unknown']
        with self.assertRaisesRegex(ValueError, 'approved logical names'):
            BenchSpec.model_validate(config)
        with TemporaryDirectory() as root, self.assertRaises(FileExistsError):
            build(BenchSpec.model_validate(bench_input()), Path(root))
