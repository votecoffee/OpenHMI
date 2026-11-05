"""No-network Logix packet grouping, UDT resolution, write and SQL history checks."""

import csv
from io import StringIO
import time
from types import SimpleNamespace
import unittest
from openhmi.logix import RuntimeDriver
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
        self.assertNotIn('LevelA', driver.demands(16))

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
