"""No-network Logix packet grouping, UDT resolution, write and SQL history checks."""

import csv
from io import StringIO
from threading import Event
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from openhmi.logix import RuntimeDriver, ScanTimings
from openhmi.projects import Project, ProjectStore, default_project
from openhmi.historian import Historian, HistoryChanged
from openhmi.runtime_models import HistorianSettings
from openhmi.server import create_app
from fastapi.testclient import TestClient


class FakePLC:
    instances = []
    def __init__(self, path, **kwargs):
        self.path, self.options = path, kwargs
        self.reads, self.writes = [], []
        self.closed, self.fail = False, False
        self.values = {'Motor': {'Running': True, 'Speed': 42.0}, 'Level': 30.0}
        self.tags = {'Motor': {'external_access': 'Read/Write', 'data_type': {'name': 'MotorUDT', 'attributes': ['Running', 'Speed'], 'internal_tags': {'Running': {'data_type': 'BOOL'}, 'Speed': {'data_type': 'REAL'}}}},
                     'Level': {'external_access': 'Read/Write', 'data_type': 'REAL'}}
        self.instances.append(self)
    def open(self): return True
    def close(self): self.closed = True
    def read(self, *addresses):
        self.reads.append(addresses)
        if self.fail: raise ConnectionError('Synthetic disconnect')
        result = []
        for address in addresses:
            value = self.values
            for part in address.split('.'):
                value = value[part]
            result.append(SimpleNamespace(value=value, error=None))
        return result[0] if len(result) == 1 else result
    def write(self, pair):
        self.writes.append(pair)
        address, value = pair
        if '.' in address:
            root, field = address.split('.', 1)
            self.values[root][field] = value
        else: self.values[address] = value
        return SimpleNamespace(error=None)


def logix_project():
    project = default_project().model_dump()
    project.update(connections=[{'id': 'plc', 'name': 'Synthetic PLC', 'path': 'offline-only/0', 'enabled': True}],
                   tags=[{'name': 'MotorA', 'connection': 'plc', 'address': 'Motor', 'type': 'struct', 'writable': True, 'udt_type': 'MotorUDT', 'members': {'Running': 'boolean', 'Speed': 'number'}},
                         {'name': 'LevelA', 'connection': 'plc', 'address': 'Level', 'type': 'number', 'scale': 2.0, 'offset': 5.0, 'writable': True}],
                   screens=[{'id': 'fast', 'title': 'Fast', 'update_ms': 100, 'controls': [{'id': 'speed', 'kind': 'numeric', 'label': 'Speed', 'tag': 'MotorA.Speed'}]},
                            {'id': 'slow', 'title': 'Slow', 'update_ms': 1000, 'controls': [{'id': 'running', 'kind': 'indicator', 'label': 'Running', 'tag': 'MotorA.Running'}, {'id': 'level', 'kind': 'numeric', 'label': 'Level', 'tag': 'LevelA'}]}])
    return Project.model_validate(project).model_dump()


class LogixHistoryTests(unittest.TestCase):
    def test_integer_values_preserve_bit_trigger_types_and_scaled_writes(self):
        project = logix_project()
        project['tags'][1]['type'] = 'integer'
        project['tags'][1]['scale'] = 1.0
        project['tags'][1]['offset'] = 0.0
        driver = RuntimeDriver(FakePLC)
        driver.configure(project)
        driver.poll(0)
        plc = driver.connections['plc'].client
        plc.values['Level'] = 30
        driver.lease('viewer', ['slow'], 1)
        driver.poll(1)
        self.assertIs(type(driver.sample_snapshot(1)['LevelA']['value']), int)
        project['tags'][1]['scale'] = 0.1
        driver.configure(project)
        driver.poll(2)
        self.assertEqual(driver.sample_snapshot(2)['LevelA']['value'], 3.0)
        driver.write('LevelA', [3.5])
        self.assertEqual(plc.writes[-1], ('Level', 35))
        self.assertIs(type(plc.writes[-1][1]), int)
        driver.close()
    def test_reconnect_backoff_is_not_extended_by_skipped_polls(self):
        driver = RuntimeDriver(FakePLC)
        driver.configure(logix_project())
        driver.lease('viewer', ['slow'], 1)
        driver.poll(1)
        connection = driver.connections['plc']
        connection.client.fail = True
        driver.poll(2)
        self.assertEqual(connection.retry_at, 3)
        driver.deadlines.clear()
        driver.poll(2.5)
        self.assertEqual(connection.retry_at, 3)
        self.assertEqual(connection.failures, 1)
        driver.poll(3.6)
        self.assertTrue(connection.connected)
        self.assertEqual(driver.sample_snapshot(3.6)['LevelA']['quality'], 'good')
        driver.close()
    def test_scan_timing_separates_read_deadlines_open_and_data_recovery(self):
        clock = SimpleNamespace(now=1.0)
        clock.monotonic = lambda: clock.now

        class TimedPLC(FakePLC):
            def open(self):
                clock.now += 0.125
                return super().open()

            def read(self, *addresses):
                clock.now += 0.25
                return super().read(*addresses)

        driver = RuntimeDriver(TimedPLC)
        self.addCleanup(driver.close)
        driver.configure(logix_project())
        driver.lease('viewer', ['slow'], 1)
        with patch('openhmi.logix.time', clock):
            driver.poll()
            connection = driver.connections['plc']
            self.assertEqual(driver.status(include_timing=True)[0]['timings']['cold_open']['last_ms'], 125)
            clock.now = 2.875  # Half a second after the first scan deadline.
            connection.client.fail = True
            driver.poll()
            self.assertEqual(connection.retry_at, 4.125)  # Backoff starts when failure is observed.
            self.assertNotIn('recovery', driver.status(include_timing=True)[0]['timings'])
            clock.now = 4.125
            driver.poll()

        status = driver.status(include_timing=True)[0]
        self.assertEqual(status['route_failures'], 1)
        self.assertEqual(status['timings']['scan']['count'], 3)
        self.assertEqual(status['timings']['scan_queue']['count'], 3)
        self.assertEqual(status['timings']['route_lock_wait']['count'], 3)
        self.assertEqual(status['timings']['adapter_read']['count'], 3)
        self.assertEqual(status['timings']['adapter_read']['p95_ms'], 250)
        self.assertEqual(status['timings']['scan']['p95_ms'], 375)
        self.assertEqual(status['timings']['scan_lateness']['p95_ms'], 500)
        self.assertEqual(status['timings']['reconnect_open']['last_ms'], 125)
        self.assertEqual(status['timings']['recovery']['last_ms'], 1375)
        self.assertNotIn('timings', driver.status()[0])

    def test_timing_window_keeps_recent_samples_and_uses_nearest_rank(self):
        timings = ScanTimings()
        for sample in range(260):
            timings.record('scan', sample / 1000)
        self.assertEqual(timings.snapshot()['scan'], {
            'count': 256, 'last_ms': 259, 'p50_ms': 131, 'p95_ms': 247, 'p99_ms': 257,
        })

    def test_shared_subscription_rates_udt_dedup_and_lease_expiry(self):
        driver = RuntimeDriver(FakePLC)
        driver.configure(logix_project())
        driver.lease('viewer1', ['slow'], 1)
        driver.lease('viewer2', ['slow'], 1)
        driver.poll(1)
        plc = driver.connections['plc'].client
        self.assertEqual(driver.connections['plc'].tag_metadata('Motor[0].Speed')['external_access'], 'Read/Write')
        self.assertEqual(driver.connections['plc'].tag_metadata('MotorOther.Speed'), {})
        self.assertEqual(plc.reads, [('Motor', 'Level')])
        self.assertEqual(driver.sample_snapshot(1)['MotorA.Speed']['value'], 42.0)
        self.assertEqual(driver.sample_snapshot(1)['LevelA']['value'], 65.0)
        driver.lease('fastViewer', ['fast'], 1.05)
        driver.poll(1.05)
        self.assertEqual(plc.reads[-1], ('Motor',))
        driver.poll(1.06)
        self.assertEqual(len(plc.reads), 2)
        driver.poll(1.16)
        self.assertEqual(plc.reads[-1], ('Motor',))
        self.assertEqual(driver.status()[0]['groups'][0]['rate_ms'], 100)
        driver.poll(20)
        self.assertEqual(len(plc.reads), 3)
        self.assertEqual(driver.sample_snapshot(20)['MotorA.Speed']['quality'], 'stale')
        driver.close()
        self.assertTrue(plc.closed)

    def test_write_readback_and_disconnect_are_not_replayed(self):
        driver = RuntimeDriver(FakePLC)
        driver.configure(logix_project())
        driver.lease('viewer', ['slow'], 1)
        driver.poll(1)
        plc = driver.connections['plc'].client
        driver.write('LevelA', [85.0])
        self.assertEqual(plc.writes, [('Level', 40.0)])
        driver.write('MotorA.Speed', [50.0])
        self.assertEqual(plc.writes[-1], ('Motor.Speed', 50.0))
        plc.fail = True
        with self.assertRaises(ConnectionError): driver.write('LevelA', [95.0])
        self.assertEqual(len(plc.writes), 3)
        self.assertIsNone(driver.connections['plc'].client)
        with self.assertRaises(ConnectionError): driver.write('LevelA', [95.0])
        self.assertEqual(len(plc.writes), 3)
        driver.poll(2)
        self.assertEqual(driver.sample_snapshot(2)['LevelA']['quality'], 'bad')
        driver.close()

    def test_tag_write_failure_keeps_route_connected_and_refreshes_affected_aliases(self):
        for rejection in (True, False):
            with self.subTest(rejection=rejection):
                project = logix_project()
                project['tags'].append({'name': 'SpeedAlias', 'connection': 'plc',
                                        'address': 'Motor.Speed', 'type': 'number'})
                project['screens'][1]['controls'].append(
                    {'id': 'speed-alias', 'kind': 'numeric', 'label': 'Speed alias', 'tag': 'SpeedAlias'})
                driver = RuntimeDriver(FakePLC)
                self.addCleanup(driver.close)
                driver.configure(Project.model_validate(project).model_dump())
                driver.lease('viewer', ['slow', 'fast'], 1)
                driver.poll(1)
                connection = driver.connections['plc']
                plc = connection.client
                error = 'Controller denied the request' if rejection else None
                message = 'PLC rejected write' if rejection else 'PLC write readback did not match'
                # The successful response in the second case leaves the observed value unchanged.
                with patch.object(plc, 'write', return_value=SimpleNamespace(error=error)) as write:
                    with self.assertRaisesRegex(ValueError, message):
                        driver.write('MotorA.Speed', [50.0])
                    write.assert_called_once_with(('Motor.Speed', 50.0))
                self.assertIs(connection.client, plc)
                self.assertFalse(plc.closed)
                self.assertEqual(connection.failure_generation, 0)
                samples = driver.sample_snapshot(1)
                for name in ('MotorA', 'MotorA.Speed', 'SpeedAlias'):
                    self.assertEqual(samples[name]['quality'], 'bad')
                    self.assertIsNone(samples[name]['value'])
                for name in ('MotorA.Running', 'LevelA'):
                    self.assertEqual(samples[name]['quality'], 'good')

                driver.poll(1.01)
                self.assertCountEqual(plc.reads[-1], ('Motor', 'Motor.Speed'))
                samples = driver.sample_snapshot(1.01)
                self.assertEqual(samples['SpeedAlias']['value'], 42.0)
                self.assertEqual(samples['MotorA.Speed']['quality'], 'good')
                self.assertEqual(plc.writes, [])

    def test_route_loss_invalidates_cached_aliases_until_fresh_reads(self):
        project = logix_project()
        project['connections'].append({**project['connections'][0], 'id': 'other', 'path': 'other-offline/0'})
        project['tags'].append({**project['tags'][1], 'name': 'OtherLevel', 'connection': 'other'})
        project['screens'][1]['update_ms'] = 5000
        project['screens'][1]['controls'].append({'id': 'other-level', 'kind': 'numeric', 'label': 'Other level', 'tag': 'OtherLevel'})
        driver = RuntimeDriver(FakePLC)
        self.addCleanup(driver.close)
        driver.configure(Project.model_validate(project).model_dump())
        driver.lease('slow-viewer', ['slow'], 1)
        driver.lease('fast-viewer', ['fast'], 1)
        driver.poll(1)
        before = driver.sample_snapshot(1)
        self.assertEqual(before['LevelA']['quality'], 'good')
        connection = driver.connections['plc']
        plc = connection.client
        plc.fail = True

        driver.poll(1.2)
        self.assertEqual(plc.reads[-1], ('Motor',))
        samples = driver.sample_snapshot(1.2)
        for name in ('MotorA', 'MotorA.Running', 'MotorA.Speed', 'LevelA'):
            self.assertEqual(samples[name]['quality'], 'bad')
            self.assertIsNone(samples[name]['value'])
        self.assertEqual(samples['LevelA']['quality_reason'], 'disconnected')
        self.assertEqual(samples['LevelA']['timestamp'], before['LevelA']['timestamp'])
        self.assertEqual(samples['OtherLevel']['quality'], 'good')

        # Reopening for metadata after the views close cannot revive old samples.
        driver.lease('slow-viewer', [], 1.3)
        driver.lease('fast-viewer', [], 1.3)
        driver.poll(2.3)
        self.assertTrue(connection.connected)
        self.assertEqual(connection.client.reads, [])
        self.assertEqual(driver.sample_snapshot(2.3)['LevelA']['quality_reason'], 'recovering')

        driver.lease('slow-viewer', ['slow'], 2.4)
        connection.client.values['Level'] = 40.0
        driver.poll(2.4)
        self.assertIn('Level', connection.client.reads[-1])
        self.assertEqual(driver.sample_snapshot(2.4)['LevelA']['value'], 85.0)
        self.assertEqual(driver.sample_snapshot(2.4)['LevelA']['quality'], 'good')
        self.assertNotIn('quality_reason', driver.sample_snapshot(2.4)['LevelA'])

    def test_background_scans_keep_healthy_routes_fresh_while_another_read_waits(self):
        blocked, release = Event(), Event()

        class BlockingPLC(FakePLC):
            def read(self, *addresses):
                if self.path == 'offline-only/0':
                    blocked.set()
                    if not release.wait(10):
                        raise ConnectionError('Test did not release the blocked read')
                return super().read(*addresses)

        project = logix_project()
        project['connections'].append({**project['connections'][0], 'id': 'other', 'path': 'other-offline/0'})
        project['tags'].append({**project['tags'][1], 'name': 'OtherLevel', 'connection': 'other'})
        project['screens'][1]['controls'].append({
            'id': 'other-level', 'kind': 'numeric', 'label': 'Other level', 'tag': 'OtherLevel',
        })
        driver = RuntimeDriver(BlockingPLC)
        self.addCleanup(driver.close)
        self.addCleanup(release.set)
        driver.configure(Project.model_validate(project).model_dump())
        driver.lease('viewer', ['slow'], 1)

        driver.poll(1, wait=False)
        self.assertTrue(blocked.wait(5))
        slow_scan = driver._scans['plc']
        driver._scans['other'].result(timeout=5)
        self.assertEqual(driver.sample_snapshot(1)['OtherLevel']['value'], 65.0)

        healthy = driver.connections['other'].client
        healthy.values['Level'] = 40.0
        driver.poll(1.5, wait=False)
        driver.poll(2, wait=False)
        driver._scans['other'].result(timeout=5)
        self.assertIs(driver._scans['plc'], slow_scan)
        self.assertFalse(slow_scan.done())
        self.assertEqual(healthy.reads, [('Level',), ('Level',)])
        self.assertEqual(driver.sample_snapshot(2)['OtherLevel']['value'], 85.0)

        # An in-flight read from the old project must not publish after Apply.
        project['tags'][1]['scale'] = 3.0
        driver.configure(Project.model_validate(project).model_dump())
        release.set()
        slow_scan.result(timeout=5)
        self.assertEqual(driver.sample_snapshot(2)['LevelA']['quality'], 'pending')
        driver.poll(2.1)
        self.assertEqual(driver.sample_snapshot(2.1)['LevelA']['value'], 95.0)
        self.assertEqual(len(driver.connections['plc'].client.reads), 2)

        with driver.write_scope(['LevelA']):
            driver.poll(3.2, wait=False)
            driver._scans['other'].result(timeout=5)
            protected_scan = driver._scans['plc']
            self.assertFalse(protected_scan.done())
            self.assertEqual(len(driver.connections['plc'].client.reads), 2)
        protected_scan.result(timeout=5)
        self.assertEqual(len(driver.connections['plc'].client.reads), 3)

    def test_chart_faceplate_tags_join_screen_subscription(self):
        project = logix_project()
        project['faceplates'] = [{'id': 'charts', 'name': 'Equipment charts', 'udt_type': 'MotorUDT',
                                  'members': {'Speed': 'number'}, 'controls': [
            {'id': 'tank', 'kind': 'tank', 'label': 'Level', 'tag': '$.Speed'},
            {'id': 'bar', 'kind': 'bar', 'label': 'Comparison', 'series': [{'tag': '$.Speed'}, {'tag': 'LevelA'}]},
            {'id': 'radar', 'kind': 'radar', 'label': 'Profile',
             'series': [{'tag': '$.Speed'}, {'tag': 'LevelA'}, {'tag': 'TankLevel'}]},
        ]}]
        project['screens'].append({'id': 'charts', 'title': 'Charts', 'update_ms': 200, 'controls': [
            {'id': 'chartpanel', 'kind': 'faceplate', 'label': 'Charts', 'template': 'charts', 'root_tag': 'MotorA'},
        ]})
        driver = RuntimeDriver(FakePLC)
        self.addCleanup(driver.close)
        driver.configure(Project.model_validate(project).model_dump())
        driver.lease('charts-station', ['charts'], 1)
        self.assertEqual({tag: driver.demands(1)[tag] for tag in ('MotorA.Speed', 'LevelA', 'TankLevel')},
                         {'MotorA.Speed': 200, 'LevelA': 200, 'TankLevel': 200})
        driver.poll(1)
        self.assertEqual(driver.connections['plc'].client.reads, [('Motor', 'Level')])
        # Apply changes to the template and scan rate while the same viewer is active.
        project['tags'].append({**project['tags'][1], 'name': 'LevelB'})
        for control in project['faceplates'][0]['controls']:
            for series in control.get('series', []):
                if series['tag'] == 'LevelA':
                    series['tag'] = 'LevelB'
        project['screens'][-1]['update_ms'] = 350
        driver.configure(Project.model_validate(project).model_dump())
        self.assertEqual(driver.demands(2),
                         {'MotorA.Speed': 350, 'LevelB': 350, 'TankLevel': 350, 'ProcessAlarm': 250})
        driver.poll(2)
        self.assertEqual(driver.sample_snapshot(2)['LevelB']['value'], 65.0)
        self.assertNotIn('LevelB', driver.demands(16))

    def test_background_history_deadband_quality_and_query(self):
        store = ProjectStore()
        driver = RuntimeDriver(FakePLC)
        project = logix_project()
        project['historian'] = {'tags': [{'tag': 'LevelA', 'sample_ms': 1000, 'deadband': 1.0}], 'retention_days': 1, 'max_rows': 1000}
        driver.configure(project)
        history = Historian(store, driver)
        history.configure(project['historian'])
        driver.poll(1)
        history.sample(1, 100)
        driver.poll(2)
        history.sample(2, 101)
        self.assertEqual(len(history.query(['LevelA'], 0, 200)['samples']), 1)
        driver.connections['plc'].client.fail = True
        driver.poll(3)
        history.sample(3, 102)
        samples = history.query(['LevelA'], 0, 200)['samples']
        self.assertEqual([row['quality'] for row in samples], ['good', 'bad'])
        self.assertIsNone(samples[-1]['value'])
        self.assertTrue(history.query(['LevelA'], 0, 200, 1)['truncated'])
        driver.close()
        store.close()

    def test_history_csv_preserves_numeric_cells_and_reports_truncation(self):
        app = create_app()
        end = int(time.time())
        with TestClient(app) as client:
            with app.state.store.transaction() as db:
                db.executemany(
                    'INSERT INTO tag_history(tag,timestamp,value,quality,source_timestamp) VALUES(?,?,?,?,?)',
                    [('TankLevel', end - 6, '999', 'good', None)]
                    + [('TankLevel', end - 5, '-2.5', 'good', None)] * 20000
                    + [('OperatorText', end - 5, '"=1+1"', 'good', None)],
                )
            response = client.get('/api/history.csv', params={
                'tags': 'TankLevel,OperatorText', 'seconds': 10, 'end': end,
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['X-OpenHMI-Truncated'], 'true')
            rows = list(csv.DictReader(StringIO(response.text)))
            self.assertEqual(len(rows), 20001)
            self.assertEqual({row['value'] for row in rows if row['tag'] == 'TankLevel'}, {'-2.5'})
            self.assertEqual(rows[-1]['value'], "'=1+1")
            full = client.get('/api/history/full.csv', params={
                'tags': 'TankLevel,OperatorText', 'start': end - 6, 'end': end,
                'project_instance': app.state.project_instance,
            })
            self.assertEqual(full.status_code, 200)
            self.assertEqual(full.headers['Content-Disposition'], 'attachment; filename="tag-history.csv"')
            complete = list(csv.DictReader(StringIO(full.text)))
            self.assertEqual(len(complete), 20002)
            self.assertEqual(complete[0]['value'], '999')
            self.assertEqual(complete[1:], rows)
            self.assertEqual(client.get('/api/history/full.csv', params={
                'tags': 'TankLevel', 'project_instance': 'different-project',
            }).status_code, 409)

    def test_complete_export_excludes_new_rows_and_rejects_pruned_rows(self):
        store = ProjectStore()
        self.addCleanup(store.close)
        history = Historian(store, None)
        with store.transaction() as db:
            db.executemany("INSERT INTO tag_history(tag,timestamp,value,quality) VALUES('TankLevel',100,?,'good')",
                           [('1',), ('2',), ('3',)])
        batches = history.export_batches(['TankLevel'], 100, 101, batch_size=1)
        self.assertEqual(next(batches)[1][0][2], '1')
        with store.transaction() as db:
            db.execute("INSERT INTO tag_history(tag,timestamp,value,quality) VALUES('TankLevel',100,'4','good')")
        self.assertEqual([rows[0][2] for _, rows in batches], ['2', '3'])
        batches = history.export_batches(['TankLevel'], 100, 101, batch_size=1)
        next(batches)
        with store.transaction() as db:
            db.execute('DELETE FROM tag_history WHERE id=2')
        with self.assertRaisesRegex(HistoryChanged, 'Retention removed'):
            list(batches)

    def test_recorded_tags_use_literal_prefix_pagination_and_latest_record(self):
        app = create_app()
        self.addCleanup(app.state.store.close)
        client = TestClient(app)
        with app.state.store.transaction() as db:
            db.executemany("INSERT INTO tag_history(tag,timestamp,value,quality) VALUES(?,?,'42','good')",
                           [('Machine.Old', 10), ('Machine.Old', 20), ('Machine.Other', 30),
                            ('MachineX', 40), ('machine.Old', 50)])
        params = {'prefix': 'Machine.', 'limit': 1, 'project_instance': app.state.project_instance}
        response = client.get('/api/history/tags', params=params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            'items': [{'tag': 'Machine.Old', 'latest': '1970-01-01T00:00:20+00:00'}],
            'next_after': 'Machine.Old',
        })
        second = client.get('/api/history/tags', params={**params, 'after': response.json()['next_after']})
        self.assertEqual(second.json(), {
            'items': [{'tag': 'Machine.Other', 'latest': '1970-01-01T00:00:30+00:00'}],
            'next_after': None,
        })
        self.assertEqual(client.get('/api/history/tags', params={**params, 'after': 'Different'}).status_code, 422)
        self.assertEqual(client.get('/api/history/tags', params={**params, 'project_instance': 'old'}).status_code, 409)

    def test_on_change_logs_transitions_deadband_and_heartbeat(self):
        store = ProjectStore()
        self.addCleanup(store.close)
        values = {
            'Run': {'value': False, 'quality': 'good'},
            'Message': {'value': 'Ready', 'quality': 'good'},
            'Speed': {'value': 10.0, 'quality': 'good'},
            'Legacy': {'value': True, 'quality': 'good'},
        }
        history = Historian(store, SimpleNamespace(sample_snapshot=lambda now: values))
        settings = HistorianSettings.model_validate({'tags': [
            {'tag': 'Run', 'mode': 'change'},
            {'tag': 'Message', 'mode': 'change'},
            {'tag': 'Speed', 'mode': 'change', 'deadband': 1.0},
            {'tag': 'Legacy'},
        ]})
        self.assertEqual(settings.tags[-1].mode, 'periodic')
        history.configure(settings.model_dump())
        history.sample(1, 101)
        values['Speed']['value'] = 10.5
        history.sample(2, 102)
        values['Speed']['value'] = 11.0
        values['Run']['value'] = True
        values['Message']['value'] = 'Running'
        history.sample(3, 103)
        values['Run']['quality'] = 'bad'
        history.sample(4, 104)
        history.sample(5, 105)
        values['Run']['quality'] = 'good'
        history.sample(6, 106)
        history.sample(66, 166)

        def recorded(tag):
            return [(row['epoch'], row['value'], row['quality']) for row in history.query([tag], 100, 170)['samples']]

        self.assertEqual(recorded('Run'), [
            (101, False, 'good'), (103, True, 'good'), (104, None, 'bad'), (106, True, 'good'), (166, True, 'good'),
        ])
        self.assertEqual(recorded('Message'), [(101, 'Ready', 'good'), (103, 'Running', 'good'), (166, 'Running', 'good')])
        self.assertEqual(recorded('Speed'), [(101, 10.0, 'good'), (103, 11.0, 'good'), (166, 11.0, 'good')])
        self.assertEqual(len(recorded('Legacy')), 7)

    def test_trend_context_uses_latest_quality_and_keeps_csv_in_range(self):
        app = create_app()
        self.addCleanup(app.state.store.close)
        client = TestClient(app)
        app.state.historian.configure(HistorianSettings.model_validate({'tags': [
            {'tag': 'MotorRunning', 'mode': 'change'},
            {'tag': 'TankLevel', 'mode': 'change'},
            {'tag': 'ProcessAlarm'},
        ]}).model_dump())
        with app.state.store.transaction() as db:
            db.executemany(
                'INSERT INTO tag_history(tag,timestamp,value,quality) VALUES(?,?,?,?)',
                [('MotorRunning', 960, 'true', 'good'), ('MotorRunning', 985, None, 'bad'),
                 ('TankLevel', 900, '42', 'good'), ('TankLevel', 992, '20', 'good'),
                 ('TankLevel', 995, '30', 'good'), ('ProcessAlarm', 989, 'false', 'good')],
            )
        params = {'tags': 'MotorRunning,TankLevel,ProcessAlarm', 'seconds': 10, 'end': 1000}
        response = client.get('/api/history', params={**params, 'trend_context': 'true'}).json()
        self.assertEqual(response['change_context'], {
            'MotorRunning': {'hold_seconds': 61.0, 'previous': {'epoch': 985.0, 'value': None, 'quality': 'bad'}},
            'TankLevel': {'hold_seconds': 61.0, 'previous': None},
        })
        self.assertNotIn('change_context', client.get('/api/history', params=params).json())
        self.assertEqual([row['value'] for row in response['samples']], [20, 30])
        rows = list(csv.DictReader(StringIO(client.get('/api/history.csv', params=params).text)))
        self.assertEqual([(row['tag'], row['value']) for row in rows], [('TankLevel', '20'), ('TankLevel', '30')])
        with app.state.store.transaction() as db:
            db.execute("INSERT INTO tag_history(tag,timestamp,value,quality) VALUES('TankLevel',980,'42','good')")
        truncated = client.get('/api/history', params={**params, 'trend_context': 'true', 'limit': 1}).json()
        self.assertTrue(truncated['truncated'])
        self.assertIsNone(truncated['change_context']['TankLevel']['previous'])

    def test_history_csv_accepts_exact_inclusive_bounds_and_rejects_invalid_ranges(self):
        app = create_app()
        self.addCleanup(app.state.store.close)
        client = TestClient(app)
        with app.state.store.transaction() as db:
            db.executemany('INSERT INTO tag_history(tag,timestamp,value,quality) VALUES(?,?,?,?)',
                           [('TankLevel', stamp, str(stamp), 'good') for stamp in range(99, 104)])
        params = {'tags': 'TankLevel', 'start': 100, 'end': 102, 'seconds': 1}
        response = client.get('/api/history.csv', params=params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['value'] for row in csv.DictReader(StringIO(response.text))], ['100', '101', '102'])
        for bounds in ({'start': 102}, {'start': 103}, {'start': -1}, {'start': 'NaN'},
                       {'end': 'inf'}, {'end': 31536101}):
            with self.subTest(bounds=bounds):
                self.assertEqual(client.get('/api/history.csv', params={**params, **bounds}).status_code, 422)

    def test_faceplate_relative_members_and_no_code_actions_server_gates(self):
        app = create_app()
        with TestClient(app) as client:
            state = client.get('/api/project').json()
            project = state['draft']
            project['tags'] = [{'name': 'UnitA', 'type': 'struct', 'initial': {'Run': False, 'Speed': 20.0}, 'members': {'Run': 'boolean', 'Speed': 'number'}, 'udt_type': 'GenericUDT', 'writable': True}]
            project['controls'].extend([{'id': 'gateToggle', 'kind': 'button', 'label': 'Gate', 'mode': 'toggle', 'target': 'UnitA.Run'},
                                        {'id': 'gatedSet', 'kind': 'button', 'label': 'Gated set', 'mode': 'set', 'target': 'TankLevel', 'value': 10, 'enabled_tag': 'UnitA.Run'}])
            project['faceplates'] = [{'id': 'Generic', 'name': 'Generic', 'udt_type': 'GenericUDT', 'members': {'Run': 'boolean', 'Speed': 'number'}, 'controls': [
                {'id': 'run', 'kind': 'button', 'label': 'Run', 'mode': 'toggle', 'target': '$.Run'},
                {'id': 'speed', 'kind': 'input', 'label': 'Speed', 'tag': '$.Speed'}]}]
            project['screens'] = [{'id': 'equipment', 'title': 'Equipment', 'controls': [{'id': 'unit', 'kind': 'faceplate', 'label': 'Unit A', 'template': 'Generic', 'root_tag': 'UnitA'}]}]
            saved = client.put('/api/project/draft', json={'expected_revision': state['draft_revision'], 'project': project})
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(client.post('/api/project/apply', json={'expected_revision': saved.json()['draft_revision']}).status_code, 200)
            self.assertEqual(client.post('/api/controls/gatedSet/activate', json={}).status_code, 423)
            self.assertEqual(client.post('/api/controls/equipment__unit__run/activate', json={}).status_code, 200)
            self.assertTrue(app.state.driver.read('UnitA.Run')[0])
            self.assertEqual(client.post('/api/controls/gatedSet/activate', json={}).status_code, 200)
            self.assertEqual(app.state.driver.read('TankLevel'), [10.0])
            self.assertEqual(client.put('/api/controls/equipment__unit__speed/value', json={'value': 45.0}).status_code, 200)
            self.assertEqual(app.state.driver.read('UnitA.Speed'), [45.0])
            self.assertEqual(client.post('/api/subscriptions', json={'client': 'a', 'screens': ['missing']}).status_code, 422)
