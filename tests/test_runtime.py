import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from fastapi.testclient import TestClient
from openhmi.drivers import SimulatorDriver
from openhmi.server import create_app


class SimulatorTests(unittest.TestCase):
    def test_read_write_and_snapshot_isolation(self):
        driver = SimulatorDriver()
        driver.write('TankLevel', [17.5])
        self.assertEqual(driver.read('TankLevel'), [17.5])
        driver.snapshot()['TankLevel'] = 99.0
        self.assertEqual(driver.read('TankLevel'), [17.5])

    def test_unknown_addresses_and_invalid_writes_do_not_create_tags(self):
        driver = SimulatorDriver()
        with self.assertRaises(KeyError):
            driver.write('Unknown', [1.0])
        for values in ([1], [True], [], [1.0, 2.0], [float('nan')], [float('inf')]):
            with self.assertRaises(ValueError):
                driver.write('TankLevel', values)
        self.assertEqual(driver.read('TankLevel'), [42.0])
        with self.assertRaises(ValueError):
            driver.read('TankLevel', 2)

    def test_app_state_isolated_and_api_read_only(self):
        app = create_app()
        other = create_app()
        app.state.driver.write('MotorRunning', [False])
        with TestClient(app) as client, TestClient(other) as second:
            self.assertFalse(client.get('/api/tags').json()['values']['MotorRunning'])
            self.assertTrue(second.get('/api/tags').json()['values']['MotorRunning'])
            self.assertEqual(client.post('/api/tags', json={}).status_code, 405)
            self.assertEqual(client.get('/').status_code, 200)
            self.assertEqual(client.get('/static/vendor/app.js').status_code, 200)

    def test_draft_apply_conflict_and_persistence(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'project.sqlite3'
            with TestClient(create_app(path)) as client:
                first = client.get('/api/project').json()
                draft = first['draft']
                draft['title'] = 'Changed while running'
                response = client.put('/api/project/draft', json={'expected_revision': 1, 'project': draft})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['draft_revision'], 2)
                self.assertEqual(client.get('/api/project/active').json()['project']['title'], 'Station overview')
                for endpoint, method in [('/api/project/draft', client.put), ('/api/project/apply', client.post)]:
                    payload = {'expected_revision': 1}
                    if endpoint.endswith('draft'):
                        payload['project'] = draft
                    self.assertEqual(method(endpoint, json=payload).status_code, 409)
                applied = client.post('/api/project/apply', json={'expected_revision': 2})
                self.assertEqual(applied.status_code, 200)
                self.assertEqual(applied.json()['active_revision'], 2)
            with TestClient(create_app(path)) as reopened:
                state = reopened.get('/api/project').json()
                self.assertEqual(state['draft']['title'], 'Changed while running')
                self.assertEqual(state['active']['title'], 'Changed while running')
                self.assertEqual(state['active_revision'], 2)

    def test_reject_bad_project_without_changing_saved_state(self):
        with TestClient(create_app()) as client:
            original = client.get('/api/project').json()
            for mutate in [
                lambda project: project.update(schema_version=2),
                lambda project: project['controls'][0].update(tag='Unknown'),
                lambda project: project['controls'][0].update(tag='MotorRunning'),
                lambda project: project['controls'][0].update(decimals=10),
                lambda project: project['controls'][0].update(html='<script/>'),
                lambda project: project['controls'][2].update(action='run_arbitrary_code'),
                lambda project: project['controls'].append(project['controls'][0].copy()),
                lambda project: project['controls'][3].update(minimum=100.0),
                lambda project: project['controls'][3].update(normal_low=90.0, normal_high=20.0),
                lambda project: project['controls'][3].update(maximum=0.0),
                lambda project: project['controls'][3].update(tag='MotorRunning'),
                lambda project: project['controls'][4].update(priority=5),
                lambda project: project['controls'][4].update(tag='TankLevel'),
            ]:
                project = client.get('/api/project').json()['draft']
                mutate(project)
                response = client.put('/api/project/draft', json={'expected_revision': 1, 'project': project})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(client.get('/api/project').json(), original)

    def test_registered_actions_and_custom_python_handler(self):
        app = create_app(handlers=Path(__file__).resolve().parents[1] / 'examples' / 'custom_actions.py')
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/actions/toggle_motor', json={}).status_code, 200)
            self.assertFalse(client.get('/api/tags').json()['values']['MotorRunning'])
            self.assertEqual(client.post('/api/actions/half_fill', json={}).status_code, 404)
            self.assertEqual(client.post('/api/actions/toggle_motor').status_code, 422)
            project = client.get('/api/project').json()['draft']
            project['controls'][2]['action'] = 'half_fill'
            client.put('/api/project/draft', json={'expected_revision': 1, 'project': project}).raise_for_status()
            client.post('/api/project/apply', json={'expected_revision': 2}).raise_for_status()
            client.post('/api/actions/half_fill', json={}).raise_for_status()
            self.assertEqual(client.get('/api/tags').json()['values']['TankLevel'], 50.0)
            self.assertFalse(client.get('/api/tags').json()['values']['MotorRunning'])

    def test_old_screen_defaults_and_new_control_round_trip(self):
        with TestClient(create_app()) as client:
            draft = client.get('/api/project').json()['draft']
            draft['controls'][1].pop('on_text')
            draft['controls'][1].pop('off_text')
            draft['controls'][3].update(minimum=-10.0, maximum=150.0, normal_low=20.0, normal_high=80.0)
            draft['controls'][4]['priority'] = 1
            response = client.put('/api/project/draft', json={'expected_revision': 1, 'project': draft})
            self.assertEqual(response.status_code, 200, response.text)
            saved = response.json()['draft']['controls']
            self.assertEqual(saved[1]['on_text'], 'ON')
            self.assertEqual(saved[3]['minimum'], -10.0)
            self.assertEqual(saved[4]['priority'], 1)


if __name__ == '__main__':
    unittest.main()
