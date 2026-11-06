from contextlib import ExitStack
from pathlib import Path
import runpy
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
                short_string = {'name': 'ShortString', 'string': 24,
                                'attributes': ['LEN'], 'internal_tags': {'LEN': {'data_type': 'DINT'}}}
                self.tags.update({
                    'Counter': {'data_type': 'ULINT', 'external_access': 'Read Only'},
                    'Names': {'data_type': short_string, 'dimensions': [3, 0, 0], 'external_access': 'Read/Write'},
                })
                motor = self.tags['Motor']['data_type']
                motor['attributes'].extend(['Label', 'Names'])
                motor['internal_tags'].update(
                    Label={'data_type': short_string}, Names={'data_type': short_string, 'array': 3})

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
            reads = list(plc.reads)
            response = client.get('/api/connections/bench/browse')
            self.assertEqual(response.status_code, 200)
            tags = {tag['address']: tag for tag in response.json()['tags']}
            self.assertEqual(tags['Counter']['numeric_range'], ['0', '18446744073709551615'])
            self.assertEqual(tags['Counter']['plc_type'], 'ULINT')
            self.assertEqual(tags['Names']['string_capacity_bytes'], 24)
            self.assertEqual(tags['Names']['dimensions'], [3, 0, 0])
            self.assertEqual(tags['Motor']['members'], {'Running': 'boolean', 'Speed': 'number', 'Label': 'string'})
            self.assertEqual(plc.reads, reads)
            before = client.get('/api/diagnostics.json').json()
            connection = before['connections'][0]
            self.assertEqual(connection['timings']['scan']['count'], 2)
            for metric in ('scan_lateness', 'scan_queue', 'route_lock_wait', 'adapter_read'):
                self.assertIn('p99_ms', connection['timings'][metric])
            self.assertEqual(connection['route_failures'], 0)
            self.assertNotIn('value', before['tags'][0])

            plc.fail = True
            driver.poll(3)
            driver.poll(4)
            after = client.get('/api/diagnostics.json').json()
            self.assertEqual(after['connections'][0]['state'], 'connected')
            self.assertEqual(after['connections'][0]['timings']['recovery']['last_ms'], 1000)
            compare = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts' / 'compare-plc-diagnostics.py'))['compare']
            with self.assertRaisesRegex(ValueError, 'failure between exports'):
                compare(before, after, 'bench')

            # Earlier exports still support a counter comparison.
            for export in (before, after):
                del export['connections'][0]['route_failures']
            self.assertGreater(compare(before, after, 'bench')['counters']['pycomm3_read_calls']['delta'], 0)

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
