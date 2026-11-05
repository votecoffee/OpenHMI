"""Timed shelving never changes PLC values, acknowledgement or alarm capture."""
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from openhmi.server import create_app
from tests.test_security import bootstrap, PASSWORD


class ShelfTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.addCleanup(self.app.state.store.close)
        self.client = TestClient(self.app)
        self.monitor = self.app.state.alarms
        self.monitor.sample()
        self.app.state.driver.write('ProcessAlarm', [True]); self.monitor.sample()
        self.identifier = self.monitor.snapshot()['outstanding'][0]['occurrence_id']
        self.path = f'/api/alarms/occurrences/{self.identifier}/shelve'

    def shelve(self, seconds=60):
        response = self.client.post(self.path, json={'duration_seconds': seconds, 'reason': 'Synthetic investigation'})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_shelving_retrigger_capture_filters_and_global_counts(self):
        with patch.object(self.app.state.driver, 'write') as write:
            result = self.shelve()
            write.assert_not_called()
        snapshot = self.monitor.snapshot()
        self.assertEqual((snapshot['active_count'], snapshot['unacknowledged_count'], snapshot['shelved_count']), (1, 1, 1))
        self.assertEqual(snapshot['annunciated_outstanding'], [])
        self.assertEqual(self.client.get('/api/alarms/occurrences?shelving=unshelved').json()['items'], [])
        self.assertEqual(len(self.client.get('/api/alarms/occurrences?shelving=shelved').json()['items']), 1)
        self.assertEqual(self.client.get('/api/alarms/occurrences?shelving=invented').status_code, 422)
        self.app.state.driver.write('ProcessAlarm', [False]); self.monitor.sample()
        self.app.state.driver.write('ProcessAlarm', [True]); self.monitor.sample()
        self.assertEqual(len(self.monitor.snapshot()['occurrences']), 2)
        self.assertEqual(self.monitor.snapshot()['annunciated_outstanding'], [])
        self.assertEqual(self.client.get('/api/alarms/shelves').json()['items'][0]['operation_id'], result['shelf_operation_id'])
        self.assertIsNone(self.monitor.snapshot()['occurrences'][0]['acknowledged_at'])

    def test_expiry_is_effective_on_reads_without_a_monitor_tick(self):
        result = self.shelve()
        later = (datetime.fromisoformat(result['expires_at']) + timedelta(seconds=1)).isoformat(timespec='milliseconds')
        with patch('openhmi.alarm_shelves.utc_now', return_value=later):
            self.assertEqual(self.client.get('/api/alarms/shelves').json()['items'], [])
            self.assertEqual(len(self.client.get('/api/alarms/occurrences?shelving=unshelved').json()['items']), 1)
            self.assertEqual(len(self.monitor.snapshot()['annunciated_outstanding']), 1)
            with patch('openhmi.alarms.utc_now', return_value=later):
                self.monitor.sample(); self.monitor.sample()
        events = self.app.state.alarm_queries.history(event='shelf_expired')['items']
        self.assertEqual(len(events), 1)
        self.assertEqual((events[0]['actor'], events[0]['provider']), ('system', 'monitor'))

    def test_restore_requires_current_shelf_identity_and_preserves_pending_alarm(self):
        first = self.shelve()
        path = '/api/alarms/shelves/process_alarm/restore'
        stale = self.client.post(path, json={'expected_operation_id': '0' * 32, 'reason': 'Stale request'})
        self.assertEqual(stale.status_code, 409)
        with patch.object(self.app.state.driver, 'write') as write:
            response = self.client.post(path, json={'expected_operation_id': first['shelf_operation_id'], 'reason': 'Investigation completed'})
            self.assertEqual(response.status_code, 200, response.text)
            write.assert_not_called()
        self.assertEqual(self.monitor.snapshot()['shelved_count'], 0)
        self.assertEqual(self.monitor.snapshot()['unacknowledged_count'], 1)
        second = self.shelve()
        self.assertNotEqual(second['shelf_operation_id'], first['shelf_operation_id'])
        self.assertEqual(self.client.post(path, json={'expected_operation_id': first['shelf_operation_id'], 'reason': 'Old page'}).status_code, 409)
        event = self.app.state.alarm_queries.history(event='shelf_restored')['items'][0]
        self.assertEqual(event['comment'], 'Investigation completed')

    def test_permission_reason_duration_and_duplicate_guards(self):
        for payload in ({'duration_seconds': 59, 'reason': 'Test'}, {'duration_seconds': 86401, 'reason': 'Test'}, {'duration_seconds': True, 'reason': 'Test'}, {'duration_seconds': 60, 'reason': '  '}, {'duration_seconds': 60, 'reason': 'x' * 1001}, {'duration_seconds': 60, 'reason': 'Test', 'actor': 'forged'}):
            self.assertEqual(self.client.post(self.path, json=payload).status_code, 422)
        bootstrap(self.app)
        self.assertEqual(self.client.post(self.path, json={'duration_seconds': 60, 'reason': 'Denied'}).status_code, 401)
        from openhmi.security_routes import SecurityChange
        security = self.app.state.security
        security.change(SecurityChange(operation='user', name='operator', groups=['Operators'], password=PASSWORD, expected_version=security.snapshot()['version'], reason='Synthetic operator'), 'test-console')
        self.client.post('/api/security/login', json={'name': 'operator', 'password': PASSWORD}).raise_for_status()
        self.assertEqual(self.client.post(self.path, json={'duration_seconds': 60, 'reason': 'Not granted'}).status_code, 403)
        self.client.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD}).raise_for_status()
        first = self.shelve()
        self.assertEqual(self.client.post(self.path, json={'duration_seconds': 120, 'reason': 'Extend'}).status_code, 409)
        item = self.client.get('/api/alarms/shelves').json()['items'][0]
        self.assertEqual((item['actor'], item['provider'], item['expires_at']), ('admin', 'local', first['expires_at']))

    def test_configuration_change_invalidates_immediately_and_records_transition(self):
        self.shelve()
        state = self.client.get('/api/project').json()
        state['draft']['alarms'][0]['priority'] = 1
        saved = self.client.put('/api/project/draft', json={'project': state['draft'], 'expected_revision': state['draft_revision']})
        self.client.post('/api/project/apply', json={'expected_revision': saved.json()['draft_revision']}).raise_for_status()
        self.assertEqual(self.client.get('/api/alarms/shelves').json()['items'], [])
        self.monitor.sample()
        self.assertEqual(len(self.app.state.alarm_queries.history(event='shelf_invalidated')['items']), 1)
        self.assertEqual(self.client.post(self.path, json={'duration_seconds': 60, 'reason': 'Obsolete occurrence'}).status_code, 409)

    def test_failed_event_storage_rolls_back_shelf_and_restore(self):
        with self.app.state.store.transaction() as db:
            db.execute("CREATE TRIGGER fail_shelf BEFORE INSERT ON alarm_event WHEN NEW.event='shelved' BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        with self.assertLogs(level='ERROR'):
            response = self.client.post(self.path, json={'duration_seconds': 60, 'reason': 'Attempt'})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.headers['X-OpenHMI-Audit-Status'], 'uncertain')
        self.assertEqual(self.client.get('/api/alarms/shelves').json()['items'], [])
        with self.app.state.store.transaction() as db:
            db.execute('DROP TRIGGER fail_shelf')
            db.execute("CREATE TRIGGER fail_restore BEFORE INSERT ON alarm_event WHEN NEW.event='shelf_restored' BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        first = self.shelve()
        with self.assertLogs(level='ERROR'):
            response = self.client.post('/api/alarms/shelves/process_alarm/restore', json={'expected_operation_id': first['shelf_operation_id'], 'reason': 'Attempt'})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(len(self.client.get('/api/alarms/shelves').json()['items']), 1)

    def test_restart_preserves_original_expiry_without_extending_interval(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'Project.sqlite3'
            app = create_app(path)
            app.state.driver.write('ProcessAlarm', [True]); app.state.alarms.sample()
            identifier = app.state.alarms.snapshot()['outstanding'][0]['occurrence_id']
            result = TestClient(app).post(f'/api/alarms/occurrences/{identifier}/shelve', json={'duration_seconds': 3600, 'reason': 'Restart fixture'}).json()
            app.state.store.close()
            restored = create_app(path)
            try:
                item = restored.state.alarms.shelves.active()['process_alarm']
                self.assertEqual(item['expires_at'], result['expires_at'])
                self.assertEqual(item['operation_id'], result['shelf_operation_id'])
            finally:
                restored.state.store.close()

    def test_registry_paging_and_sql_shelving_filters_cover_multiple_definitions(self):
        state = self.client.get('/api/project').json()
        second = {**state['draft']['alarms'][0], 'id': 'secondary_alarm'}
        state['draft']['alarms'].append(second)
        saved = self.client.put('/api/project/draft', json={'project': state['draft'], 'expected_revision': state['draft_revision']})
        self.client.post('/api/project/apply', json={'expected_revision': saved.json()['draft_revision']}).raise_for_status()
        self.monitor.sample()
        for occurrence in self.monitor.snapshot()['outstanding']:
            self.client.post(f'/api/alarms/occurrences/{occurrence["occurrence_id"]}/shelve', json={'duration_seconds': 60, 'reason': 'Paging fixture'}).raise_for_status()
        page = self.client.get('/api/alarms/shelves?limit=1').json()
        self.assertTrue(page['has_more'])
        next_page = self.client.get('/api/alarms/shelves', params={'limit': 1, 'after_id': page['next_after_id']}).json()
        self.assertNotEqual(page['items'][0]['alarm_id'], next_page['items'][0]['alarm_id'])
        self.assertFalse(next_page['has_more'])
        self.assertEqual(len(self.client.get('/api/alarms/occurrences?shelving=shelved').json()['items']), 2)
        self.assertEqual(self.client.get('/api/alarms/occurrences?shelving=unshelved').json()['items'], [])

    def test_complete_backup_restores_shelves_with_original_expiry(self):
        from openhmi.workspace import ProjectWorkspace
        with TemporaryDirectory() as directory:
            workspace = ProjectWorkspace(Path(directory) / 'Original.openhmi.sqlite3')
            with TestClient(workspace) as client:
                workspace.current.state.driver.write('ProcessAlarm', [True]); workspace.current.state.alarms.sample()
                identifier = workspace.current.state.alarms.snapshot()['outstanding'][0]['occurrence_id']
                result = client.post(f'/api/alarms/occurrences/{identifier}/shelve', json={'duration_seconds': 3600, 'reason': 'Backup fixture'}).json()
                backup = client.get('/api/workspace/backup')
                client.post('/api/workspace/import?name=Restored', content=backup.content).raise_for_status()
                client.post('/api/workspace/open', json={'file': 'Restored.openhmi.sqlite3'}).raise_for_status()
                shelf = client.get('/api/alarms/shelves').json()['items'][0]
                self.assertEqual(shelf['expires_at'], result['expires_at'])
                self.assertEqual(shelf['reason'], 'Backup fixture')
                self.assertTrue(client.get('/api/tags').json()['plc_hold'])
