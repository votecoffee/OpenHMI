"""Read-only diagnostics boundaries across catalog replacement and route faults."""
from threading import RLock
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

from openhmi.diagnostics import runtime_diagnostics


class SnapshotBoundary:
    """Apply a replacement immediately after the snapshot releases its lock."""
    def __init__(self, released):
        self.lock = RLock()
        self.owned = False
        self.released = released

    def __enter__(self):
        self.lock.acquire()
        self.owned = True

    def __exit__(self, *args):
        self.owned = False
        self.lock.release()
        self.released()


class DiagnosticsTests(unittest.TestCase):
    def test_snapshot_uses_one_catalog_generation_and_releases_before_worker_health(self):
        driver = SimpleNamespace(
            sources={'Motor.Running': ('Motor', 'Running')},
            definitions={'Motor': {'connection': 'plc', 'address': 'OldMotor',
                                   'type': 'struct', 'members': {'Running': 'boolean'}}},
            project={'connections': [{'id': 'plc', 'name': 'Old route', 'path': 'offline-old', 'enabled': True}]},
            plc_hold=False)
        def replace():
            driver.sources = {}
            driver.definitions = {}
            driver.project = {'connections': [{'id': 'new', 'name': 'New route', 'path': 'offline-new', 'enabled': True}]}
            driver.plc_hold = True
        boundary = SnapshotBoundary(replace)
        driver.lock = boundary
        observed = []
        def samples(now, *, include_values):
            self.assertTrue(boundary.owned)
            self.assertFalse(include_values)
            observed.append(now)
            return {'Motor.Running': {'quality': 'good', 'value_type': 'boolean',
                                      'value': 'must not be projected', 'timestamp': None}}
        def status(*, include_timing, now):
            self.assertTrue(boundary.owned)
            self.assertTrue(include_timing)
            self.assertEqual(observed, [now])
            return [{'id': 'plc', 'connected': True, 'connection_instance': 'old-instance',
                     'read_calls': 2, 'tags_read': 3, 'timings': {'scan': {'count': 1}}}]
        driver.sample_snapshot, driver.status = Mock(side_effect=samples), Mock(side_effect=status)
        def workers():
            self.assertFalse(boundary.owned)
            self.assertEqual(driver.project['connections'][0]['id'], 'new')
            return [{'id': 'acquisition', 'state': 'healthy'}]
        result = runtime_diagnostics(driver, SimpleNamespace(snapshot=workers))
        tag, = result['tags']
        self.assertEqual((tag['address'], tag['type'], tag['connection']), ('OldMotor.Running', 'boolean', 'plc'))
        self.assertNotIn('value', tag)
        self.assertEqual(tag['age_seconds'], 0)
        route, = result['connections']
        self.assertEqual((route['path'], route['state'], route['connection_instance']),
                         ('offline-old', 'connected', 'old-instance'))
        self.assertFalse(result['plc_hold'])
        self.assertEqual(result['workers'][0]['state'], 'healthy')
        driver.sample_snapshot.assert_called_once()
        driver.status.assert_called_once()

    def test_fault_precedence_filters_and_paging_keep_diagnostics_value_free(self):
        samples = {'设备.Level': {'quality': 'bad', 'value_type': 'number', 'error': 'Bad binding'},
                   'Local': {'quality': 'good', 'value_type': 'string'},
                   'Pending': {'quality': 'pending', 'value_type': 'boolean'}}
        config = {'id': 'plc', 'name': 'Offline route', 'path': 'offline-only', 'enabled': True}
        driver = SimpleNamespace(lock=RLock(), sources={'设备.Level': ('Level', '')},
            definitions={'Level': {'connection': 'plc', 'address': 'Level', 'type': 'number'}},
            project={'connections': [config]}, plc_hold=False,
            sample_snapshot=Mock(return_value=samples), status=Mock(return_value=[]))
        workers = SimpleNamespace(snapshot=lambda: [])
        precedence = [({}, 'disconnected'), ({'connected': True}, 'connected'),
            ({'connected': True, 'data_unavailable': True}, 'no usable data'),
            ({'data_unavailable': True, 'awaiting_data': True}, 'waiting for first good data'),
            ({'awaiting_data': True, 'recovering': True}, 'recovering'),
            ({'recovering': True, 'scan_overdue': True}, 'scan overdue')]
        for flags, expected in precedence:
            with self.subTest(state=expected):
                driver.status.return_value = [{'id': 'plc', **flags}]
                self.assertEqual(runtime_diagnostics(driver, workers)['connections'][0]['state'], expected)
        driver.plc_hold = True
        self.assertEqual(runtime_diagnostics(driver, workers)['connections'][0]['state'], 'held')
        config['enabled'] = False
        self.assertEqual(runtime_diagnostics(driver, workers)['connections'][0]['state'], 'disabled')
        first = runtime_diagnostics(driver, workers, quality='non-good', limit=1)
        second = runtime_diagnostics(driver, workers, quality='non-good', offset=1, limit=1)
        self.assertEqual(first['total_tags'], 2)
        self.assertEqual((first['tags'][0]['name'], first['next_offset'], first['truncated']), ('Pending', 1, True))
        self.assertEqual((second['tags'][0]['name'], second['next_offset'], second['truncated']), ('设备.Level', None, False))
        local = runtime_diagnostics(driver, workers, connection_filter=':local')
        self.assertEqual({row['name'] for row in local['tags']}, {'Local', 'Pending'})
        source = runtime_diagnostics(driver, workers, search='LEVEL', connection_filter='plc')
        self.assertEqual(source['tags'][0]['address'], 'Level')
        self.assertIsNone(source['tags'][0]['age_seconds'])
        self.assertEqual(runtime_diagnostics(driver, workers, offset=100)['tags'], [])


if __name__ == '__main__':
    unittest.main()
