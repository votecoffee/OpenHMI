"""Actual HTTP identity headers through the production opt-in runtime reader."""
import json
import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient
from openhmi.server import create_app
from tests.test_frontend_contract import frontend


class BrowserProjectIdentityTests(unittest.TestCase):
    def fixture(self):
        app = create_app(hold_connections=True)
        self.addCleanup(app.state.store.close)
        self.addCleanup(app.state.driver.close)
        app.state.driver.factory = Mock(side_effect=AssertionError('Offline test cannot contact a PLC'))
        client = TestClient(app)  # No background acquisition/lifespan required.
        self.addCleanup(client.close)
        return app, client

    def wire(self, response):
        return dict(status=response.status_code, headers=dict(response.headers), body=response.text)

    def test_real_same_project_reads_accept_but_other_project_data_never_rebinds_or_retries(self):
        original, client = self.fixture()
        replacement, other = self.fixture()
        paths = ['/api/tags', '/api/tags?status_only=true', '/api/alarms', '/api/recipes/selected', '/api/security/session', '/api/catalog']
        initial = self.wire(client.get('/api/project'))
        same, foreign = [self.wire(client.get(path)) for path in paths], [self.wire(other.get(path)) for path in paths]
        self.assertTrue(all(reply['status'] == 200 for reply in same + foreign))
        stale = other.post('/api/controls/toggle/activate', json={}, headers={'X-OpenHMI-Project': original.state.project_instance})
        self.assertEqual(stale.status_code, 409)
        result = frontend('http_context', requests=[dict(path='/api/project')] + [dict(path=path, runtime=True) for path in paths * 2]
                          + [dict(path='/api/controls/toggle/activate', options={'method': 'POST'})],
                          replies=[initial, *same, *foreign, self.wire(stale)])
        self.assertTrue(all('data' in row for row in result['results'][1:7]))
        self.assertTrue(all(row.get('project_context') and row['project_changed'] and 'data' not in row for row in result['results'][7:13]))
        self.assertTrue(result['results'][-1]['conflict'])
        self.assertEqual(len(result['calls']), 14)
        for call in result['calls'][1:]:
            self.assertEqual(call['headers']['X-OpenHMI-Project'], original.state.project_instance)
            self.assertNotIn('unexpected_project_read_option', call)
        self.assertEqual(replacement.state.activity.query()['items'], [])
        original.state.driver.factory.assert_not_called(); replacement.state.driver.factory.assert_not_called()

    def test_missing_malformed_headers_reject_before_json_and_matching_source_recovers(self):
        app, client = self.fixture()
        initial = self.wire(client.get('/api/project'))
        good = self.wire(client.get('/api/tags'))
        replies = []
        for source in (None, '', 'short', 'F' * 32, 'f' * 32):
            headers = {key: value for key, value in good['headers'].items() if key != 'x-openhmi-project'}
            if source is not None: headers['x-openhmi-project'] = source
            replies.append(dict(status=200, headers=headers, body='not JSON; identity must be checked first'))
        result = frontend('http_context', requests=[dict(path='/api/project')] + [dict(path='/api/tags', runtime=True) for _ in replies + [good]],
                          replies=[initial, *replies, good])
        self.assertTrue(all(row.get('project_context') and 'data' not in row for row in result['results'][1:-1]))
        self.assertEqual([row['project_changed'] for row in result['results'][1:-1]], [False] * 4 + [True])
        self.assertEqual(result['results'][-1]['data'], json.loads(good['body']))
        self.assertEqual(len(result['calls']), 7)

    def test_alarm_console_reads_keep_source_even_when_occurrence_ids_collide(self):
        original, client = self.fixture()
        replacement, other = self.fixture()
        identifiers = []
        for app in (original, replacement):
            monitor = app.state.alarms
            monitor.sample_values = Mock(return_value={'ProcessAlarm': True})
            monitor.sample()
            identifier = monitor.snapshot()['outstanding'][0]['occurrence_id']
            monitor.note(identifier, 'Source-specific recovery note', ('Fixture Operator', 'local'), '1' * 32)
            monitor.shelves.begin(identifier, 900, 'Source-specific investigation', ('Fixture Operator', 'local'), '2' * 32)
            identifiers.append(identifier)
        self.assertEqual(identifiers[0], identifiers[1])
        identifier = identifiers[0]
        paths = ['/api/alarms/occurrences?state=all&shelving=all', '/api/alarms/events?event=operator_note',
                 f'/api/alarms/occurrences/{identifier}', f'/api/alarms/occurrences/{identifier}/notes',
                 '/api/alarms/shelves?after_id=']
        same = [self.wire(client.get(path)) for path in paths]
        foreign = [self.wire(other.get(path)) for path in paths]
        missing = [{**reply, 'headers': {key: value for key, value in reply['headers'].items()
                                       if key != 'x-openhmi-project'}} for reply in same]
        self.assertTrue(all(reply['status'] == 200 for reply in same + foreign))
        calls_before = [app.state.alarms.sample_values.call_count for app in (original, replacement)]
        stale = other.post(f'/api/alarms/{identifier}/acknowledge', json={'comment': 'Old screen'},
                           headers={'X-OpenHMI-Project': original.state.project_instance})
        self.assertEqual(stale.status_code, 409)
        result = frontend('http_context', requests=[dict(path='/api/project')]
                          + [dict(path=path, runtime=True) for path in paths * 4]
                          + [dict(path=f'/api/alarms/{identifier}/acknowledge', options={'method': 'POST'})],
                          replies=[self.wire(client.get('/api/project')), *same, *foreign, *missing, *same, self.wire(stale)])
        for index in (1, 16):
            self.assertEqual([row['data'] for row in result['results'][index:index + 5]],
                             [json.loads(reply['body']) for reply in same])
        for row in result['results'][6:16]:
            self.assertTrue(row['project_context'])
            self.assertNotIn('data', row)
        self.assertEqual([row['project_changed'] for row in result['results'][6:16]], [True] * 5 + [False] * 5)
        self.assertTrue(result['results'][-1]['conflict'])
        self.assertEqual(len(result['calls']), 22, 'Read failures cannot replay acknowledgements')
        self.assertTrue(all(call['headers']['X-OpenHMI-Project'] == original.state.project_instance
                            for call in result['calls'][1:]))
        self.assertEqual(calls_before, [app.state.alarms.sample_values.call_count for app in (original, replacement)])
        self.assertEqual(replacement.state.activity.query()['items'], [])
        self.assertIsNone(replacement.state.alarm_queries.detail(identifier)['occurrence']['acknowledged_at'])
        original.state.driver.factory.assert_not_called(); replacement.state.driver.factory.assert_not_called()

    def test_applied_project_change_is_readable_only_with_coherent_header_body_without_repinning(self):
        app, client = self.fixture()
        replacement, other = self.fixture()
        initial = self.wire(client.get('/api/project'))
        current = self.wire(client.get('/api/project/active'))
        changed = self.wire(other.get('/api/project/active'))
        mismatch = {**changed, 'headers': current['headers']}
        reverse = {**current, 'headers': changed['headers']}
        tag = self.wire(client.get('/api/tags'))
        result = frontend('http_context', requests=[dict(path='/api/project')] + [dict(path='/api/project/active', runtime=True) for _ in range(4)]
                          + [dict(path='/api/tags', runtime=True)], replies=[initial, current, changed, mismatch, reverse, tag])
        self.assertEqual(result['results'][2]['data']['project_instance'], replacement.state.project_instance)
        self.assertTrue(all(row.get('project_context') and 'data' not in row for row in result['results'][3:5]))
        self.assertEqual(result['results'][-1]['data'], json.loads(tag['body']))
        self.assertTrue(all(call['headers']['X-OpenHMI-Project'] == app.state.project_instance for call in result['calls'][1:]))

    def test_command_reads_reject_foreign_completion_with_same_transaction_id_without_dispatch(self):
        from openhmi.alarms import utc_now
        original, client = self.fixture()
        replacement, other = self.fixture()
        for app, state in ((original, 'uncertain'), (replacement, 'completed')):
            stamp = utc_now()
            with app.state.store.transaction() as db:
                cursor = db.execute('''INSERT INTO command_transaction(operation_id,command_id,channel,signature,
                    definition_json,sequence,state,created_at,updated_at,deadline) VALUES(?,?,?,?,?,?,?,?,?,?)''',
                    ('identity-operation', 'identity_cycle', 'offline', 'fixture', '{}', 1, state, stamp, stamp, stamp))
                self.assertEqual(cursor.lastrowid, 1)
                app.state.commands._update(db, 1, state, 'Offline source-specific evidence', 0 if state == 'completed' else None)
        paths = ['/api/commands?limit=50&command_id=identity_cycle', '/api/commands/1',
                 '/api/commands?command_id=identity_cycle&limit=1']
        same = [self.wire(client.get(path)) for path in paths]
        foreign = [self.wire(other.get(path)) for path in paths]
        missing = [{**reply, 'headers': {key: value for key, value in reply['headers'].items()
                                       if key != 'x-openhmi-project'}} for reply in same]
        self.assertTrue(all(reply['status'] == 200 for reply in same + foreign))
        requests = [dict(path=paths[0], runtime=True), dict(path=paths[1], runtime=True),
                    dict(latestCommand='identity_cycle')]
        from unittest.mock import patch
        with patch.object(replacement.state.driver, 'write', side_effect=AssertionError('No command replay')) as write, \
             patch.object(replacement.state.activity, 'run', side_effect=AssertionError('No stale dispatch')) as journal:
            stale = other.post('/api/controls/cycle/activate', json={},
                               headers={'X-OpenHMI-Project': original.state.project_instance})
            self.assertEqual(stale.status_code, 409)
            write.assert_not_called(); journal.assert_not_called()
        result = frontend('http_context', requests=[dict(path='/api/project')] + requests * 4
                          + [dict(path='/api/controls/cycle/activate', options={'method': 'POST'})],
                          replies=[self.wire(client.get('/api/project')), *same, *foreign, *missing, *same, self.wire(stale)])
        for start in (1, 10):
            self.assertEqual([row['data'] for row in result['results'][start:start + 3]],
                             [json.loads(reply['body']) for reply in same])
        self.assertTrue(all(row.get('project_context') and 'data' not in row for row in result['results'][4:10]))
        self.assertEqual([row['project_changed'] for row in result['results'][4:10]], [True] * 3 + [False] * 3)
        self.assertTrue(result['results'][-1]['conflict'])
        self.assertEqual(len(result['calls']), 14)
        self.assertTrue(all(call['headers']['X-OpenHMI-Project'] == original.state.project_instance
                            for call in result['calls'][1:]))
        self.assertEqual(replacement.state.commands.get(1)['state'], 'completed')
        self.assertEqual(replacement.state.activity.query()['items'], [])
        original.state.driver.factory.assert_not_called(); replacement.state.driver.factory.assert_not_called()

    def test_uninitialized_and_invalid_read_modes_never_dispatch_and_http_errors_remain_errors(self):
        app, client = self.fixture()
        from tests.test_security import bootstrap
        bootstrap(app)
        initial = self.wire(client.get('/api/project'))
        denied = self.wire(client.get('/api/security'))
        self.assertEqual(denied['status'], 401)
        requests = [dict(path='/api/tags', runtime=True), dict(path='/api/tags', options={'projectRead': 'unknown'}),
                    dict(path='/api/tags', options={'projectRead': 'same', 'method': 'POST'}), dict(path='/api/project'),
                    dict(path='/api/security', runtime=True)]
        result = frontend('http_context', requests=requests, replies=[initial, denied])
        self.assertEqual(len(result['calls']), 2)
        self.assertTrue(all('data' not in row for row in result['results'][:3]))
        self.assertTrue(result['results'][0]['project_context'])
        self.assertEqual(result['results'][-1]['status'], 401)
        self.assertNotIn('project_context', result['results'][-1])

    def test_activity_and_diagnostics_helpers_keep_source_across_filtered_pages(self):
        from starlette.requests import Request
        original, client = self.fixture()
        replacement, other = self.fixture()
        for app, entity in ((original, 'Original 设备'), (replacement, 'Foreign 设备')):
            ticket = app.state.activity.start(Request({'type': 'http', 'headers': []}), 'offline_fixture', entity, {})
            app.state.activity.finish(ticket.id, 'succeeded', {}, '')
        self.assertEqual(original.state.activity.query()['items'][0]['id'],
                         replacement.state.activity.query()['items'][0]['id'])
        paths = ['/api/activity?limit=1', '/api/activity?before_id=1&limit=1',
                 '/api/diagnostics?quality=all&offset=0&limit=1', '/api/diagnostics?quality=all&offset=1&limit=1']
        requests = [dict(activity={'options': {'limit': 1}}), dict(activity={'before': 1, 'options': {'limit': 1}}),
                    dict(diagnostics={'criteria': {'quality': 'all'}, 'offset': 0, 'options': {'limit': 1}}),
                    dict(diagnostics={'criteria': {'quality': 'all'}, 'offset': 1, 'options': {'limit': 1}})]
        same = [self.wire(client.get(path)) for path in paths]
        foreign = [self.wire(other.get(path)) for path in paths]
        missing = [{**reply, 'headers': {key: value for key, value in reply['headers'].items()
                                       if key != 'x-openhmi-project'}} for reply in same]
        self.assertTrue(all(reply['status'] == 200 for reply in same + foreign))
        result = frontend('http_context', requests=[dict(path='/api/project')] + requests * 4,
                          replies=[self.wire(client.get('/api/project')), *same, *foreign, *missing, *same])
        for start in (1, 13):
            self.assertEqual([row['data'] for row in result['results'][start:start + 4]],
                             [json.loads(reply['body']) for reply in same])
        self.assertTrue(all(row.get('project_context') and 'data' not in row for row in result['results'][5:13]))
        self.assertEqual([row['project_changed'] for row in result['results'][5:13]], [True] * 4 + [False] * 4)
        self.assertEqual(len(result['calls']), 17)
        for index, call in enumerate(result['calls'][1:]):
            self.assertEqual(call['path'], paths[index % 4])
            self.assertEqual(call['method'], 'GET')
            self.assertEqual(call['headers']['X-OpenHMI-Project'], original.state.project_instance)
        for app in (original, replacement):
            self.assertEqual(len(app.state.activity.query()['items']), 1, 'Read recovery cannot append operator actions')
            app.state.driver.factory.assert_not_called()
