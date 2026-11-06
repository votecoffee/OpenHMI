import csv
from io import StringIO
from pathlib import Path
import sqlite3
import time
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from openhmi.server import create_app
from tests.test_security import bootstrap, PASSWORD
from tests.test_logix_history import logix_project, FakePLC


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        state = self.client.get('/api/project').json()
        state['draft']['controls'].append({'id': 'setpoint', 'kind': 'input', 'label': 'Setpoint', 'tag': 'TankLevel'})
        saved = self.client.put('/api/project/draft', json={'expected_revision': state['draft_revision'], 'project': state['draft']})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.client.post('/api/project/apply', json={'expected_revision': saved.json()['draft_revision']}).raise_for_status()

    def rows(self):
        return self.app.state.activity.query()['items']

    def test_success_receipts_context_and_no_duplicate_python_record(self):
        result = self.client.put('/api/controls/setpoint/value', json={'value': 23.5})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.headers['X-OpenHMI-Audit-Status'], 'succeeded')
        record = self.rows()[0]
        self.assertEqual(result.headers['X-OpenHMI-Operation-ID'], record['operation_id'])
        self.assertEqual(record['actor'], 'unsecured-simulation')
        self.assertEqual(record['context']['before']['value'], 42.0)
        self.assertEqual(record['context']['before']['quality'], 'good')
        self.assertEqual(record['context']['requested_value'], 23.5)
        self.assertEqual(record['context']['tag'], 'TankLevel')
        self.assertEqual(record['outcome']['verification'], 'local_write')
        self.client.post('/api/controls/toggle/activate', json={}).raise_for_status()
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(self.rows()[0]['outcome']['verification'], 'callback_returned')
        self.client.post('/api/alarms/acknowledge-all', json={}).raise_for_status()
        self.assertEqual(self.rows()[0]['outcome']['verification'], 'alarm_acknowledged')
        self.assertEqual(self.client.post('/api/alarms/99999/acknowledge', json={}).status_code, 404)
        self.assertEqual(self.rows()[0]['status'], 'rejected')
        self.assertEqual(self.rows()[0]['phase'], 'prepared')

    def test_denied_actor_and_limit_rejections_are_server_attributed(self):
        bootstrap(self.app)
        self.client.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD}).raise_for_status()
        security = self.app.state.security
        self.client.put('/api/security', json={'operation': 'user', 'expected_version': security.snapshot()['version'], 'name': 'operator', 'groups': ['Operators'], 'password': PASSWORD, 'reason': 'Synthetic account'}).raise_for_status()
        self.client.post('/api/security/login', json={'name': 'operator', 'password': PASSWORD}).raise_for_status()
        response = self.client.put('/api/controls/setpoint/value', json={'value': 75.0})
        self.assertEqual(response.status_code, 403)
        denied = self.rows()[0]
        self.assertEqual((denied['actor'], denied['provider'], denied['groups'], denied['status']), ('operator', 'local', ['Operators'], 'denied'))
        self.assertEqual(denied['context']['tag'], 'TankLevel')
        self.assertEqual(self.client.get('/api/activity').status_code, 403)
        self.assertEqual(self.client.get('/api/diagnostics').status_code, 403)
        self.client.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD}).raise_for_status()
        result = self.client.put('/api/controls/setpoint/value', json={'value': 150.0})
        self.assertEqual(result.status_code, 422)
        self.assertEqual(self.rows()[0]['status'], 'rejected')
        self.assertEqual(self.app.state.driver.read('TankLevel'), [42.0])
        payload = self.client.get('/api/activity').text
        self.assertNotIn(PASSWORD, payload)
        self.assertNotIn(self.client.cookies.get('openhmi_session'), payload)
        from tests.test_security import FakeWindows
        security.windows = FakeWindows()
        for change in ({'operation': 'windows', 'enabled': True}, {'operation': 'binding', 'account': 'EXAMPLE\\Maintainers', 'kind': 'group', 'group': 'Engineers'}):
            self.client.put('/api/security', json={**change, 'expected_version': security.snapshot()['version'], 'reason': 'Synthetic Windows assignment'}).raise_for_status()
        self.client.post('/api/security/login', json={'name': 'EXAMPLE\\person', 'password': PASSWORD, 'provider': 'windows'}).raise_for_status()
        self.client.put('/api/controls/setpoint/value', json={'value': 18.0}).raise_for_status()
        windows = self.rows()[0]
        self.assertEqual((windows['actor'], windows['provider'], windows['groups']), ('EXAMPLE\\person', 'windows', ['Engineers']))

    def test_stale_button_revision_is_journaled_before_python_dispatch(self):
        state = self.client.get('/api/project').json()
        button = next(control for control in state['draft']['controls'] if control['id'] == 'toggle')
        button['label'] = 'Updated motor button'
        saved = self.client.put('/api/project/draft', json={'expected_revision': state['draft_revision'], 'project': state['draft']})
        saved.raise_for_status()
        applied = self.client.post('/api/project/apply', json={'expected_revision': saved.json()['draft_revision']})
        applied.raise_for_status()
        active_revision = applied.json()['active_revision']
        self.assertGreater(active_revision, state['active_revision'])
        path = '/api/controls/toggle/activate'
        with patch.object(self.app.state.application, 'invoke') as invoke:
            result = self.client.post(path, json={'expected_revision': state['active_revision']})
            self.assertEqual(result.status_code, 409, result.text)
            invoke.assert_not_called()
        record, = self.rows()
        self.assertEqual((record['status'], record['phase']), ('rejected', 'prepared'))
        self.assertEqual(record['context']['expected_revision'], state['active_revision'])
        self.assertEqual(record['context']['active_revision'], active_revision)
        self.client.post(path, json={'expected_revision': active_revision}).raise_for_status()
        self.assertEqual(self.rows()[0]['outcome']['verification'], 'callback_returned')

    def test_dispatch_failure_is_uncertain_and_never_replayed(self):
        def partial_write(address, values):
            self.app.state.driver._tags[address] = values[0]
            raise ConnectionError('Synthetic lost readback')
        with patch.object(self.app.state.driver, 'write', side_effect=partial_write) as write:
            response = self.client.put('/api/controls/setpoint/value', json={'value': 30.0})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.headers['X-OpenHMI-Audit-Status'], 'uncertain')
            self.assertIn('verify before retrying', response.text)
            self.app.state.activity.maintenance(force=True)
            self.assertEqual(write.call_count, 1)
        self.assertEqual(self.app.state.driver.read('TankLevel'), [30.0])
        self.assertEqual(self.rows()[0]['status'], 'uncertain')

    def test_python_partial_failure_is_uncertain_without_leaking_exception_details(self):
        def partial(app):
            app.driver.write('TankLevel', [17.0])
            raise RuntimeError('Synthetic private callback detail')
        self.app.state.application.register_action('partial', 'Partial callback', partial)
        state = self.client.get('/api/project').json()
        state['draft']['controls'][2]['action'] = 'partial'
        saved = self.client.put('/api/project/draft', json={'expected_revision': state['draft_revision'], 'project': state['draft']}).json()
        self.client.post('/api/project/apply', json={'expected_revision': saved['draft_revision']}).raise_for_status()
        with self.assertLogs(level='ERROR'):
            response = self.client.post('/api/controls/toggle/activate', json={})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers['X-OpenHMI-Audit-Status'], 'uncertain')
        self.assertNotIn('private callback detail', response.text)
        self.assertEqual(self.app.state.driver.read('TankLevel'), [17.0])
        self.assertEqual(self.rows()[0]['status'], 'uncertain')

    def test_non_python_binding_cannot_authorize_a_legacy_python_action(self):
        state = self.client.get('/api/project').json()
        state['draft']['controls'][2].update(mode='toggle', target='MotorRunning')
        saved = self.client.put('/api/project/draft', json={'expected_revision': state['draft_revision'], 'project': state['draft']}).json()
        self.client.post('/api/project/apply', json={'expected_revision': saved['draft_revision']}).raise_for_status()
        self.assertEqual(self.client.post('/api/actions/toggle_motor', json={'control_id': 'toggle'}).status_code, 404)
        self.assertTrue(self.app.state.driver.read('MotorRunning')[0])
        self.assertEqual(self.client.post('/api/controls/toggle/activate', json={}).status_code, 200)
        self.assertFalse(self.app.state.driver.read('MotorRunning')[0])

    def test_unavailable_attempt_or_dispatch_storage_prevents_execution(self):
        for method in ('start', 'mark_dispatch'):
            with patch.object(self.app.state.activity, method, side_effect=sqlite3.OperationalError('Synthetic database failure')):
                response = self.client.post('/api/controls/toggle/activate', json={})
                self.assertEqual(response.status_code, 503)
                self.assertIn('not dispatched', response.text)
                self.assertTrue(self.app.state.driver.read('MotorRunning')[0])

    def test_finalization_failure_preserves_confirmed_response_then_repairs_only_journal(self):
        journal = self.app.state.activity
        journal.last_maintenance = time.monotonic()
        with patch.object(journal, 'finish', side_effect=sqlite3.OperationalError('Synthetic finalization failure')):
            with self.assertLogs(level='ERROR'):
                result = self.client.post('/api/controls/toggle/activate', json={})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.headers['X-OpenHMI-Audit-Status'], 'pending')
        self.assertFalse(self.app.state.driver.read('MotorRunning')[0])
        self.assertEqual(self.rows()[0]['status'], 'pending')
        journal.maintenance(force=True)
        self.assertEqual(self.rows()[0]['status'], 'succeeded')
        self.assertEqual(journal.query()['pending_finalizations'], 0)
        self.assertFalse(self.app.state.driver.read('MotorRunning')[0])

    def test_restart_classifies_prepared_and_dispatched_without_replaying(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'project.sqlite3'
            app = create_app(path)
            with TestClient(app):
                request = SimpleNamespace(cookies={}, client=SimpleNamespace(host='synthetic'))
                prepared = app.state.activity.start(request, 'test', 'prepared', {})
                dispatched = app.state.activity.start(request, 'test', 'dispatched', {})
                dispatched.dispatch()
            restarted = create_app(path)
            with TestClient(restarted):
                rows = {row['operation_id']: row for row in restarted.state.activity.query()['items']}
                self.assertEqual(rows[prepared.id]['status'], 'interrupted')
                self.assertEqual(rows[dispatched.id]['status'], 'uncertain')
                self.assertTrue(restarted.state.driver.read('MotorRunning')[0])

    def test_query_export_retention_and_old_admin_permissions(self):
        for _ in range(5):
            self.client.post('/api/controls/toggle/activate', json={}).raise_for_status()
        first = self.client.get('/api/activity?limit=2').json()
        second = self.client.get(f"/api/activity?limit=2&before_id={first['next_before_id']}").json()
        self.assertTrue(first['has_more'])
        self.assertFalse({row['id'] for row in first['items']} & {row['id'] for row in second['items']})
        identifier = first['items'][0]['operation_id']
        self.assertEqual(len(self.client.get('/api/activity', params={'search': identifier}).json()['items']), 1)
        self.assertEqual(self.client.get('/api/activity?start=invalid').status_code, 422)
        self.assertEqual(self.client.get('/api/activity?status=invalid').status_code, 422)
        self.assertEqual(self.client.get('/api/activity', params={'before_id': 2 ** 80}).status_code, 422)
        with self.app.state.store.transaction() as db:
            db.execute("UPDATE operator_activity SET error='=1+1',status='uncertain',started_at='2000-01-01T00:00:00+00:00' WHERE operation_id=?", (identifier,))
            resolved_id = first['items'][1]['operation_id']
            db.execute("UPDATE operator_activity SET started_at='2000-01-01T00:00:00+00:00' WHERE operation_id=?", (resolved_id,))
        exported = self.client.get('/api/activity.csv')
        self.assertEqual(list(csv.DictReader(StringIO(exported.text)))[0]['error'], "'=1+1")
        self.app.state.activity.maintenance(force=True)
        self.assertEqual(self.client.get('/api/activity', params={'search': identifier}).json()['items'][0]['status'], 'uncertain')
        self.assertFalse(self.client.get('/api/activity', params={'search': resolved_id}).json()['items'])
        bootstrap(self.app)
        with self.app.state.store.transaction() as db:
            db.execute("UPDATE security_group SET permissions='[\"security.manage\"]' WHERE name='Administrators'")
        self.client.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD}).raise_for_status()
        self.assertEqual(self.client.get('/api/activity').status_code, 200)
        self.assertEqual(self.client.get('/api/diagnostics').status_code, 200)

    def test_diagnostics_can_isolate_one_connection_or_local_tags(self):
        driver = self.app.state.driver
        project = logix_project()
        project['connections'][0]['enabled'] = False
        project['connections'].append({**project['connections'][0], 'id': 'local'})
        project['tags'].append({**project['tags'][1], 'name': 'OtherLevel', 'connection': 'local'})
        driver.configure(project)

        filters = {'search': 'level', 'quality': 'bad', 'connection': 'local', 'limit': 1}
        filtered = self.client.get('/api/diagnostics', params=filters).json()
        self.assertEqual(filtered['total_tags'], 1)
        self.assertIsNone(filtered['next_offset'])
        self.assertEqual([tag['name'] for tag in filtered['tags']], ['OtherLevel'])
        self.assertEqual({route['id'] for route in filtered['connections']}, {'plc', 'local'})

        exported = self.client.get('/api/diagnostics.json', params={'connection': 'plc', 'quality': 'bad'}).json()
        self.assertTrue(exported['tags'])
        self.assertTrue(all(tag['connection'] == 'plc' for tag in exported['tags']))
        local_tags = self.client.get('/api/diagnostics', params={'connection': ':local', 'search': 'TankLevel'}).json()['tags']
        self.assertEqual([(tag['name'], tag['connection']) for tag in local_tags], [('TankLevel', '')])
        self.assertFalse(driver.connections)

    def test_diagnostics_held_and_disabled_are_read_only_and_omit_values(self):
        driver = self.app.state.driver
        driver.plc_hold = True
        driver.configure(logix_project())
        with patch.object(driver, 'lease', side_effect=AssertionError('Diagnostics must not subscribe')):
            response = self.client.get('/api/diagnostics', params={'search': 'LevelA'})
            self.assertEqual(response.status_code, 200, response.text)
            result = response.json()
            self.assertEqual(result['connections'][0]['state'], 'held')
            self.assertEqual(result['tags'][0]['quality'], 'bad')
            self.assertNotIn('value', result['tags'][0])
            self.assertEqual(result['tags'][0]['error'], 'PLC acquisition is held')
            filtered = self.client.get('/api/diagnostics', params={'quality': 'non-good', 'limit': 1}).json()
            self.assertEqual(filtered['total_tags'], 4)
            self.assertEqual(filtered['next_offset'], 1)
            self.assertEqual(filtered['tags'][0]['name'], 'LevelA')
            next_page = self.client.get('/api/diagnostics', params={'quality': 'non-good', 'limit': 1, 'offset': 1}).json()
            self.assertEqual(next_page['tags'][0]['name'], 'MotorA')
            exported = self.client.get('/api/diagnostics.json', params={'quality': 'bad', 'search': 'level'}).json()
            self.assertEqual([tag['name'] for tag in exported['tags']], ['LevelA'])
            self.assertNotIn('value', exported['tags'][0])
            self.assertNotIn('values', exported)
            self.assertEqual(exported['capture']['project_instance'], self.app.state.project_instance)
            self.assertGreater(exported['capture']['monotonic_seconds'], 0)
            self.assertFalse(driver.connections)
        project = logix_project()
        project['connections'][0]['enabled'] = False
        driver.configure(project)
        self.assertEqual(self.client.get('/api/diagnostics').json()['connections'][0]['state'], 'disabled')
        driver.plc_hold = False
        driver.factory = FakePLC
        driver.configure(logix_project())
        connection = self.client.get('/api/diagnostics.json').json()['connections'][0]
        self.assertEqual(connection['connection_instance'], driver.connections['plc'].instance)
        self.assertEqual(self.client.get('/api/diagnostics?search=LevelA').json()['tags'][0]['quality'], 'pending')
        with driver.lock:
            driver.samples['LevelA'] = {'value': 1.0, 'quality': 'good', 'timestamp': '2026-11-04T00:00:00+00:00', 'monotonic': time.monotonic() - 10, 'rate_ms': 100, 'error': None}
        stale = self.client.get('/api/diagnostics?search=LevelA&quality=stale').json()['tags'][0]
        self.assertEqual(stale['quality'], 'stale')
        self.assertGreaterEqual(stale['age_seconds'], 10)
        with driver.lock:
            driver.samples['LevelA'].update(quality='bad', error='Synthetic source error')
        self.assertEqual(self.client.get('/api/diagnostics?search=LevelA').json()['tags'][0]['error'], 'Synthetic source error')
