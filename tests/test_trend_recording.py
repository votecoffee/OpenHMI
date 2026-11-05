"""Deterministic offline capture, rollover, trigger and restore checks."""

import csv
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest

from fastapi.testclient import TestClient

from openhmi.logix import RuntimeDriver
from openhmi.projects import Project, ProjectStore
from openhmi.trend_recording import TrendRecorder
from openhmi.workspace import ProjectWorkspace
from tests.test_logix_history import FakePLC, logix_project


def apply(client, project):
    state = client.get('/api/project').json()
    result = client.put('/api/project/draft', json={'expected_revision': state['draft_revision'], 'project': project})
    if not result.is_success:
        return result
    return client.post('/api/project/apply', json={'expected_revision': result.json()['draft_revision']})


class TrendRecordingTests(unittest.TestCase):
    def test_sampled_triggers_without_viewer_and_scaled_values(self):
        project = logix_project()
        project['tags'][1]['type'] = 'integer'
        project['tags'].append({'name': 'StartCapture', 'type': 'boolean', 'initial': True, 'writable': True})
        project['controls'].append({'id': 'trend', 'kind': 'trend', 'label': 'Test trend',
                                    'tags': ['LevelA', 'MotorA.Running'],
                                    'recording': {'sample_ms': 100, 'max_samples': 10,
                                                  'start_tag': 'StartCapture', 'stop_tag': 'MotorA.Running'}})
        project = Project.model_validate(project).model_dump()
        driver = RuntimeDriver(FakePLC)
        driver.configure(project)
        store = ProjectStore()
        self.addCleanup(store.close)
        self.addCleanup(driver.close)
        recorder = TrendRecorder(store, driver)
        recorder.configure(project)
        driver.poll(1)
        recorder.sample(1, 100)
        self.assertEqual(driver.trend_demands, {'StartCapture': 100, 'MotorA.Running': 100})
        self.assertFalse(recorder.listing('trend')['captures'])
        plc = driver.connections['plc'].client
        plc.values['Level'] = 30
        plc.values['Motor']['Running'] = False
        driver.write('StartCapture', [False])
        driver.poll(2)
        recorder.sample(2, 101)
        driver.write('StartCapture', [True])
        driver.poll(3)
        recorder.sample(3, 102)
        self.assertIn('LevelA', driver.demands(3))
        driver.poll(4)
        recorder.sample(4, 103)
        plc.values['Motor']['Running'] = True
        driver.poll(5)
        recorder.sample(5, 104)
        capture, = recorder.listing('trend')['captures']
        self.assertEqual(capture['reason'], 'stop trigger')
        self.assertNotIn('LevelA', driver.demands(5))
        data = recorder.history(capture['id'], 10, None)
        self.assertEqual(data['end'], 103)
        self.assertEqual([(row['tag'], row['value'], row['quality']) for row in data['samples']],
                         [('LevelA', None, 'pending'), ('MotorA.Running', False, 'good'),
                          ('LevelA', 65.0, 'good'), ('MotorA.Running', False, 'good')])
        recorder.sample(6, 105)
        self.assertEqual(len(recorder.listing('trend')['captures']), 1)
        self.assertFalse(plc.writes)

    def test_rollover_view_window_csv_and_backup_restore(self):
        with TemporaryDirectory() as directory:
            workspace = ProjectWorkspace(Path(directory) / 'Original.openhmi.sqlite3')
            client = TestClient(workspace.current)
            try:
                project = client.get('/api/project').json()['active']
                trend = {'id': 'trend', 'kind': 'trend', 'label': 'Test capture', 'tags': ['TankLevel', 'MotorRunning'],
                         'seconds': 60, 'recording': {'sample_ms': 100, 'max_samples': 10, 'start_tag': 'TankLevel'}}
                project['controls'].append(trend)
                self.assertEqual(apply(client, project).status_code, 422)
                trend['recording']['start_tag'] = ''
                self.assertEqual(apply(client, project).status_code, 200)
                recorder = workspace.current.state.trends
                response = client.post('/api/trends/trend', json={'action': 'start'})
                self.assertEqual(response.status_code, 200, response.text)
                identifier = response.json()['id']
                self.assertEqual(client.post('/api/trends/trend', json={'action': 'start'}).json()['id'], identifier)
                start = time.time() - 20
                for index in range(13):
                    recorder.sample(index, start + index)
                trend['seconds'] = 10
                self.assertEqual(apply(client, project).status_code, 200)
                capture, = recorder.listing('trend')['captures']
                self.assertEqual((capture['retained'], capture['rolled_off'], capture['stopped']), (10, 3, None))
                self.assertEqual(client.post('/api/trends/trend', json={'action': 'stop', 'capture_id': identifier + 1}).status_code, 409)
                self.assertEqual(client.post('/api/trends/trend', json={'action': 'stop', 'capture_id': identifier}).status_code, 200)
                base = f'/api/trend-captures/{identifier}'
                self.assertEqual(len(client.get(base, params={'seconds': 2}).json()['samples']), 6)
                exported = client.get(base + '/csv')
                self.assertEqual(exported.status_code, 200)
                rows = list(csv.DictReader(StringIO(exported.text)))
                self.assertEqual(len(rows), 20)
                self.assertEqual({row['value'] for row in rows}, {'42.0', 'true'})
                workspace.import_backup('Restored', workspace.export())
                restored = workspace._app(Path(directory) / 'Restored.openhmi.sqlite3')
                try:
                    restored_client = TestClient(restored)
                    self.assertEqual(restored_client.get(base + '/csv').content, exported.content)
                    self.assertEqual(restored_client.post('/api/trends/trend', json={'action': 'start'}).status_code, 409)
                    self.assertEqual(restored_client.post('/api/trends/trend', json={'action': 'delete', 'capture_id': identifier}).status_code, 200)
                    self.assertEqual(restored_client.get(base).status_code, 404)
                finally:
                    restored.state.store.close()
                self.assertEqual(client.get(base + '/csv').content, exported.content)
                unfinished = client.post('/api/trends/trend', json={'action': 'start'}).json()['id']
                recorder.sample(20, time.time())
                reopened = workspace._app(workspace.path)
                try:
                    latest, previous = reopened.state.trends.listing('trend')['captures']
                    self.assertEqual((latest['id'], latest['reason'], latest['retained']), (unfinished, 'interrupted', 1))
                    self.assertEqual(previous['retained'], 10)
                finally:
                    reopened.state.store.close()
            finally:
                workspace.current.state.store.close()
