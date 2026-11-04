"""No-network Logix packet grouping, UDT resolution, write and SQL history checks."""

from types import SimpleNamespace
import unittest
from openhmi.logix import RuntimeDriver
from openhmi.projects import Project, ProjectStore, default_project
from openhmi.historian import Historian
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
    def test_shared_subscription_rates_udt_dedup_and_lease_expiry(self):
        driver = RuntimeDriver(FakePLC)
        driver.configure(logix_project())
        driver.lease('viewer1', ['slow'], 1)
        driver.lease('viewer2', ['slow'], 1)
        driver.poll(1)
        plc = driver.connections['plc'].client
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

    def test_faceplate_relative_members_and_no_code_actions_server_gates(self):
        app = create_app()
        with TestClient(app) as client:
            state = client.get('/api/project').json()
            project = state['draft']
            project['tags'] = [{'name': 'UnitA', 'type': 'struct', 'initial': {'Run': False, 'Speed': 20.0}, 'members': {'Run': 'boolean', 'Speed': 'number'}, 'udt_type': 'GenericUDT', 'writable': True}]
            project['faceplates'] = [{'id': 'Generic', 'name': 'Generic', 'udt_type': 'GenericUDT', 'members': {'Run': 'boolean', 'Speed': 'number'}, 'controls': [
                {'id': 'run', 'kind': 'button', 'label': 'Run', 'mode': 'toggle', 'target': '$.Run'},
                {'id': 'speed', 'kind': 'input', 'label': 'Speed', 'tag': '$.Speed'}]}]
            project['screens'] = [{'id': 'equipment', 'title': 'Equipment', 'controls': [{'id': 'unit', 'kind': 'faceplate', 'label': 'Unit A', 'template': 'Generic', 'root_tag': 'UnitA'}]}]
            saved = client.put('/api/project/draft', json={'expected_revision': state['draft_revision'], 'project': project})
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(client.post('/api/project/apply', json={'expected_revision': saved.json()['draft_revision']}).status_code, 200)
            self.assertEqual(client.post('/api/controls/equipment__unit__run/activate', json={}).status_code, 200)
            self.assertTrue(app.state.driver.read('UnitA.Run')[0])
            self.assertEqual(client.put('/api/controls/equipment__unit__speed/value', json={'value': 45.0}).status_code, 200)
            self.assertEqual(app.state.driver.read('UnitA.Speed'), [45.0])
            self.assertEqual(client.post('/api/subscriptions', json={'client': 'a', 'screens': ['missing']}).status_code, 422)
