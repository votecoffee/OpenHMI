"""Operator alarm contracts, attribution, retention and additive migration."""
import csv
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from openhmi.alarms import AlarmMonitor
from openhmi.alarm_queries import AlarmQueries
from openhmi.projects import Project, ProjectStore, RevisionRequest, SaveRequest
from openhmi.server import create_app
from tests.test_security import bootstrap, PASSWORD


class AlarmWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.addCleanup(self.app.state.store.close)
        # No lifespan thread: every sample below is deliberate and deterministic.
        self.client = TestClient(self.app)
        self.monitor = self.app.state.alarms
        self.queries = self.app.state.alarm_queries
        self.monitor.sample()

    def raise_alarm(self):
        self.app.state.driver.write('ProcessAlarm', [True])
        self.monitor.sample()
        return self.queries.occurrences()['items'][0]['occurrence_id']

    def apply(self, edit):
        state = self.app.state.store.snapshot()
        project = Project.model_validate(state['active'])
        edit(project)
        saved = self.app.state.store.save(SaveRequest(expected_revision=state['draft_revision'], project=project))
        self.app.state.store.apply(RevisionRequest(expected_revision=saved['draft_revision']))

    def test_alarm_snapshot_marks_overdue_evaluation_and_recovers(self):
        with patch('openhmi.alarms.monotonic', return_value=100.0) as clock:
            identifier = self.raise_alarm()
            clock.return_value = 104.9
            self.assertFalse(self.client.get('/api/alarms').json()['evaluation_stale'])
            clock.return_value = 105.0
            stale = self.client.get('/api/alarms').json()
            self.assertTrue(stale['evaluation_stale'])
            self.assertEqual(stale['outstanding'][0]['occurrence_id'], identifier)
            self.monitor.sample()
            self.assertFalse(self.client.get('/api/alarms').json()['evaluation_stale'])

    def test_alarm_snapshot_identifies_the_revision_last_evaluated(self):
        first = self.app.state.store.snapshot()['active_revision']
        self.assertEqual(self.client.get('/api/alarms').json()['sampled_revision'], first)
        self.apply(lambda project: setattr(project, 'title', 'Changed alarm project'))
        current = self.app.state.store.snapshot()['active_revision']
        self.assertGreater(current, first)
        self.assertEqual(self.client.get('/api/alarms').json()['sampled_revision'], first)
        self.monitor.sample()
        self.assertEqual(self.client.get('/api/alarms').json()['sampled_revision'], current)

    def test_detail_explains_cached_trigger_loss_without_returning_the_alarm(self):
        identifier = self.raise_alarm()
        driver = self.app.state.driver
        sample = {'value': False, 'quality': 'bad', 'quality_reason': 'disconnected',
                  'timestamp': '2026-01-01T12:00:00Z', 'age_seconds': 4.5, 'error': 'Synthetic route loss'}
        with patch.object(driver, 'sample_snapshot', return_value={'ProcessAlarm': sample}), \
                patch.object(driver, 'poll') as poll, patch.object(driver, 'write') as write:
            self.monitor.sample()
            response = self.client.get(f'/api/alarms/occurrences/{identifier}')
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertTrue(data['occurrence']['active'])
            self.assertIsNone(data['occurrence']['returned_at'])
            self.assertEqual(data['trigger'], {key: value for key, value in sample.items() if key != 'value'})
            poll.assert_not_called()
            write.assert_not_called()

        self.monitor.sample()
        recovered = self.client.get(f'/api/alarms/occurrences/{identifier}').json()
        self.assertTrue(recovered['occurrence']['active'])
        self.assertEqual(recovered['trigger']['quality'], 'good')

    def test_first_ack_identity_is_server_owned_and_idempotent_without_plc_write(self):
        identifier = self.raise_alarm()
        bootstrap(self.app)
        self.client.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD}).raise_for_status()
        path = f'/api/alarms/{identifier}/acknowledge'
        with patch.object(self.app.state.driver, 'write') as write:
            response = self.client.post(path, json={'comment': 'Investigating'})
            self.assertEqual(response.status_code, 200, response.text)
            first = self.queries.detail(identifier)['occurrence']
            again = self.client.post(path, json={'comment': 'Replacement'})
            self.assertEqual(again.json()['acknowledged'], [])
            self.assertEqual(self.queries.detail(identifier)['occurrence'], first)
            write.assert_not_called()
        self.assertEqual((first['acknowledged_by'], first['acknowledged_provider']), ('admin', 'local'))
        self.assertEqual(first['acknowledgement_operation_id'], response.headers['X-OpenHMI-Operation-ID'])
        self.assertEqual(first['acknowledgement_comment'], 'Investigating')
        self.assertTrue(first['active'])
        self.assertEqual(self.client.post(path, json={'actor': 'forged'}).status_code, 422)

    def test_selected_ack_is_atomic_and_explicit(self):
        identifier = self.raise_alarm()
        endpoint = '/api/alarms/acknowledge-selected'
        result = self.client.post(endpoint, json={'occurrence_ids': [identifier, 999999]})
        self.assertEqual(result.status_code, 404, result.text)
        self.assertIsNone(self.queries.detail(identifier)['occurrence']['acknowledged_at'])
        self.assertEqual(self.app.state.activity.query()['items'][0]['phase'], 'prepared')
        for identifiers in ([], [identifier, identifier], [0], [2**63], list(range(1, 202))):
            self.assertEqual(self.client.post(endpoint, json={'occurrence_ids': identifiers}).status_code, 422)
        self.assertEqual(self.client.post(endpoint, json={'occurrence_ids': [identifier]}).json()['acknowledged'], [identifier])

    def test_notes_require_permission_and_keep_append_only_actor_and_receipt(self):
        identifier = self.raise_alarm()
        endpoint = f'/api/alarms/occurrences/{identifier}/notes'
        bootstrap(self.app)
        self.assertEqual(self.client.post(endpoint, json={'comment': 'Denied'}).status_code, 401)
        self.client.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD}).raise_for_status()
        for comment in ('', '   ', 'x' * 1001):
            self.assertEqual(self.client.post(endpoint, json={'comment': comment}).status_code, 422)
        for comment in ('Inspecting supply', 'Supply restored'):
            response = self.client.post(endpoint, json={'comment': comment})
            self.assertEqual(response.status_code, 200, response.text)
        notes = self.client.get(endpoint, params={'limit': 1}).json()
        self.assertTrue(notes['has_more'])
        latest = notes['items'][0]
        self.assertEqual((latest['actor'], latest['provider'], latest['comment']), ('admin', 'local', 'Supply restored'))
        self.assertEqual(latest['operation_id'], response.headers['X-OpenHMI-Operation-ID'])
        older = self.client.get(endpoint, params={'limit': 1, 'before_id': notes['next_before_id']}).json()
        self.assertEqual(older['items'][0]['comment'], 'Inspecting supply')
        self.assertEqual(self.client.delete(endpoint).status_code, 405)
        self.assertEqual(self.client.post('/api/alarms/occurrences/99999/notes', json={'comment': 'Missing'}).status_code, 404)

    def test_note_failure_rolls_back_note_and_event_with_uncertain_receipt(self):
        identifier = self.raise_alarm()
        with self.app.state.store.transaction() as db:
            db.execute("CREATE TRIGGER reject_note_event BEFORE INSERT ON alarm_event WHEN NEW.event='operator_note' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with self.assertLogs(level='ERROR'):
            response = self.client.post(f'/api/alarms/occurrences/{identifier}/notes', json={'comment': 'Not committed'})
        self.assertEqual(response.status_code, 500, response.text)
        self.assertEqual(response.headers['X-OpenHMI-Audit-Status'], 'uncertain')
        self.assertEqual(self.queries.notes(identifier)['items'], [])
        self.assertEqual(self.queries.history(event='operator_note')['items'], [])

    def test_guidance_is_captured_at_raise_and_does_not_retrigger(self):
        def configure(project):
            project.alarms[0].cause = 'Low pressure'
            project.alarms[0].response = 'Inspect supply'
            project.languages[0].translations['alarm.process_alarm.cause'] = 'Translated cause'
        self.apply(configure)
        identifier = self.raise_alarm()
        self.apply(lambda project: setattr(project.alarms[0], 'cause', 'Updated cause'))
        self.monitor.sample()
        detail = self.client.get(f'/api/alarms/occurrences/{identifier}').json()
        self.assertEqual(detail['occurrence']['cause'], 'Low pressure')
        self.assertEqual(detail['occurrence']['causes']['en'], 'Translated cause')
        self.assertEqual(detail['occurrence']['response'], 'Inspect supply')
        self.assertNotIn('value', detail['trigger'])
        self.assertEqual(len(self.queries.occurrences()['items']), 1)

    def test_bounded_filters_literal_search_dates_and_event_attribution(self):
        self.apply(lambda project: setattr(project.alarms[0], 'message', 'Pressure 50%_low'))
        first = self.raise_alarm()
        self.monitor.acknowledge(first, identity=('Operator', 'local'), comment='=unsafe formula')
        self.app.state.driver.write('ProcessAlarm', [False]); self.monitor.sample()
        second = self.raise_alarm()
        endpoint = '/api/alarms/occurrences'
        page = self.client.get(endpoint, params={'state': 'all', 'limit': 1}).json()
        self.assertEqual(page['items'][0]['occurrence_id'], second)
        self.assertTrue(page['has_more'])
        older = self.client.get(endpoint, params={'state': 'all', 'before_id': page['next_before_id']}).json()
        self.assertEqual([row['occurrence_id'] for row in older['items']], [first])
        self.assertEqual(len(self.client.get(endpoint, params={'search': '%_'}).json()['items']), 1)
        self.assertEqual(self.client.get(endpoint, params={'search': '50X_low'}).json()['items'], [])
        self.assertEqual(self.client.get(endpoint, params={'state': 'returned'}).json()['items'][0]['occurrence_id'], first)
        for params in ({'state': 'invented'}, {'limit': 201}, {'start': '2026-01-01'}, {'start': '2026-02-01T00:00:00Z', 'end': '2026-01-01T00:00:00Z'}):
            self.assertEqual(self.client.get(endpoint, params=params).status_code, 422)
        self.assertEqual(self.client.get(endpoint, params={'start': '2000-01-01T03:00:00+03:00'}).status_code, 200)
        event = self.queries.history(event='acknowledged')['items'][0]
        self.assertEqual((event['actor'], event['comment']), ('Operator', '=unsafe formula'))
        exported = self.client.get('/api/alarms/events.csv', params={'event': 'acknowledged'})
        self.assertEqual(exported.headers['X-OpenHMI-Truncated'], 'false')
        row = list(csv.DictReader(StringIO(exported.text)))[0]
        self.assertTrue(row['comment'].startswith("'="))

    def test_old_database_migrates_without_inventing_acknowledgement_identity(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'legacy.sqlite3'
            store = ProjectStore(path)
            monitor = AlarmMonitor(store, lambda: {'ProcessAlarm': True})
            monitor.sample(); monitor.acknowledge()
            with store.transaction() as db:
                for table in ('alarm_note', 'alarm_acknowledgement', 'alarm_event_context'):
                    db.execute(f'DROP TABLE {table}')
            store.close()
            restored = ProjectStore(path)
            try:
                queries = AlarmQueries(AlarmMonitor(restored, lambda: {'ProcessAlarm': True}))
                item = queries.occurrences()['items'][0]
                self.assertIsNotNone(item['acknowledged_at'])
                self.assertIsNone(item['acknowledged_by'])
                self.assertIsNone(queries.history(event='acknowledged')['items'][0]['actor'])
            finally:
                restored.close()

    def test_retention_keeps_pending_notes_and_prunes_completed_companions(self):
        self.apply(lambda project: setattr(project, 'alarm_history_limit', 50))
        first = self.raise_alarm()
        self.monitor.note(first, 'Pending investigation', ('Operator', 'local'), 'note-op')
        for _ in range(51):
            self.app.state.driver.write('ProcessAlarm', [False]); self.monitor.sample()
            current = self.raise_alarm()
            self.monitor.acknowledge(current)
        self.assertEqual(self.queries.notes(first)['items'][0]['comment'], 'Pending investigation')
        self.monitor.acknowledge(first)
        self.monitor.sample()
        with self.assertRaises(KeyError):
            self.queries.detail(first)
        with self.app.state.store._lock:
            db = self.app.state.store._db
            self.assertEqual(db.execute('SELECT COUNT(*) FROM alarm_note WHERE occurrence_id=?', (first,)).fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM alarm_event_context WHERE event_id NOT IN (SELECT id FROM alarm_event)').fetchone()[0], 0)

    def test_automatic_acknowledgement_is_explicit(self):
        self.apply(lambda project: setattr(project.alarms[0], 'ack_required', False))
        identifier = self.raise_alarm()
        occurrence = self.queries.detail(identifier)['occurrence']
        self.assertEqual((occurrence['acknowledged_by'], occurrence['acknowledged_provider']), ('system', 'automatic'))
        self.assertEqual(occurrence['acknowledged_at'], occurrence['raised_at'])

    def test_comment_permission_is_independent_from_acknowledgement(self):
        from openhmi.security_routes import SecurityChange
        identifier = self.raise_alarm()
        bootstrap(self.app)
        security = self.app.state.security
        for change in ({'operation': 'group', 'name': 'Commenters', 'permissions': ['alarms.comment']},
                       {'operation': 'user', 'name': 'reviewer', 'groups': ['Commenters'], 'password': PASSWORD}):
            security.change(SecurityChange(**change, expected_version=security.snapshot()['version'], reason='Synthetic test'), 'test-console')
        self.client.post('/api/security/login', json={'name': 'reviewer', 'password': PASSWORD}).raise_for_status()
        self.assertEqual(self.client.post(f'/api/alarms/{identifier}/acknowledge', json={}).status_code, 403)
        self.assertEqual(self.client.post(f'/api/alarms/occurrences/{identifier}/notes', json={'comment': 'Review only'}).status_code, 200)
        self.assertIsNone(self.queries.detail(identifier)['occurrence']['acknowledged_at'])

    def test_csv_export_is_bounded_and_reports_truncation(self):
        with self.app.state.store.transaction() as db:
            db.executemany('INSERT INTO alarm_event(occurrence_id,alarm_id,event,timestamp) VALUES(NULL,?,?,?)',
                           [('orphan', 'quality_bad', '2026-01-01T00:00:00.000+00:00')] * 20001)
        response = self.client.get('/api/alarms/events.csv', params={'search': 'orphan'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['X-OpenHMI-Truncated'], 'true')
        self.assertEqual(len(list(csv.DictReader(StringIO(response.text)))), 20000)
        self.assertEqual(self.queries.history(state='active')['items'], [])
        self.assertEqual(self.queries.history(state='unacknowledged')['items'], [])

    def test_backup_restores_notes_and_first_acknowledgement(self):
        from openhmi.workspace import ProjectWorkspace
        with TemporaryDirectory() as directory:
            workspace = ProjectWorkspace(Path(directory) / 'Original.openhmi.sqlite3')
            with TestClient(workspace) as client:
                app = workspace.current
                app.state.driver.write('ProcessAlarm', [True]); app.state.alarms.sample()
                identifier = app.state.alarm_queries.occurrences()['items'][0]['occurrence_id']
                app.state.alarms.note(identifier, 'Retained note', ('Person', 'local'), 'note-operation')
                app.state.alarms.acknowledge(identifier, identity=('Person', 'local'), operation_id='ack-operation')
                backup = client.get('/api/workspace/backup')
                self.assertEqual(backup.status_code, 200)
                imported = client.post('/api/workspace/import?name=Restored', content=backup.content)
                self.assertEqual(imported.status_code, 200, imported.text)
                client.post('/api/workspace/open', json={'file': 'Restored.openhmi.sqlite3'}).raise_for_status()
                detail = workspace.current.state.alarm_queries.detail(identifier)
                self.assertEqual(detail['occurrence']['acknowledgement_operation_id'], 'ack-operation')
                self.assertEqual(detail['occurrence']['acknowledged_by'], 'Person')
                self.assertEqual(detail['notes']['items'][0]['operation_id'], 'note-operation')
