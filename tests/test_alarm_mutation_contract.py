"""Actual browser mutation payloads through secured SQL-backed alarm routes."""
import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openhmi.activity import ActivityJournal
from openhmi.alarm_routes import add_alarm_routes
from openhmi.alarms import AlarmMonitor
from openhmi.projects import ProjectStore
from openhmi.security import COOKIE, Security
from openhmi.security_routes import SecurityChange
from tests.test_frontend_contract import frontend
from tests.test_security import FakeWindows, PASSWORD


class AlarmMutationContractTests(unittest.TestCase):
    def setUp(self):
        self.store = ProjectStore()
        self.addCleanup(self.store.close)
        self.security = Security(self.store, windows=FakeWindows())
        self.change('user', name='admin', groups=['Administrators'], password=PASSWORD)
        self.change('group', name='Readers', permissions=[])
        self.change('user', name='reader', groups=['Readers'], password=PASSWORD)
        self.journal = ActivityJournal(self.store, self.security)
        self.source = Mock(return_value={'ProcessAlarm': True})
        self.monitor = AlarmMonitor(self.store, self.source)
        self.monitor.sample()
        self.identifier = self.monitor.snapshot()['outstanding'][0]['occurrence_id']
        self.driver = Mock(spec=['sample_snapshot'])
        app = FastAPI()
        add_alarm_routes(app, self.monitor, self.security, self.journal, self.driver, self.store)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.queries = app.state.alarm_queries
        for owner, name in ((self.monitor, 'note'), (self.monitor.shelves, 'begin'), (self.monitor.shelves, 'restore')):
            setattr(owner, name, Mock(wraps=getattr(owner, name)))

    def change(self, operation, **kwargs):
        self.security.change(SecurityChange(operation=operation, expected_version=self.security.snapshot()['version'],
                                            reason='Offline contract fixture', **kwargs), 'test-console')

    def login(self, name):
        token, _ = self.security.login(name, PASSWORD, 'test-console')
        self.client.cookies.set(COOKIE, token)

    def browser(self, mutations, **kwargs):
        return frontend('alarm_mutations', mutations=mutations, **kwargs)

    def send(self, request):
        self.assertEqual(request['method'], 'POST')
        self.assertTrue(request['timed'])
        self.assertEqual(request['headers']['X-OpenHMI-Project'], 'a' * 32)
        return self.client.post(request['path'], json=request['body'])

    def mutations(self):
        return [dict(action='note', id=str(self.identifier), comment=' 设备 recovery\nStep 2 '),
                dict(action='shelve', id=str(self.identifier), duration='60', reason=' Investigate '),
                dict(action='restore', id='process_alarm', expected='0' * 32, reason=' Restore ')]

    def assert_no_acquisition(self):
        self.source.assert_called_once_with()
        self.driver.sample_snapshot.assert_not_called()

    def test_generated_payloads_attribution_and_stale_restore_preserve_alarm_state(self):
        self.login('admin')
        requests = self.browser(self.mutations())['requests']
        note = self.send(requests[0])
        self.assertEqual(note.status_code, 200, note.text)
        saved = self.queries.notes(self.identifier)['items'][0]
        self.assertEqual((saved['actor'], saved['provider'], saved['comment']),
                         ('admin', 'local', self.mutations()[0]['comment']))
        self.assertEqual(requests[1]['body'], {'duration_seconds': 60, 'reason': ' Investigate '})
        shelf = self.send(requests[1])
        self.assertEqual(shelf.status_code, 200, shelf.text)
        operation = shelf.json()['shelf_operation_id']
        self.assertEqual(self.send(requests[2]).status_code, 409)
        self.assertEqual(self.monitor.shelves.active()['process_alarm']['operation_id'], operation)
        restore = self.browser([dict(action='restore', id='process_alarm', expected=operation, reason=' Restore ')])
        self.assertEqual(self.send(restore['requests'][0]).status_code, 200)
        self.assertEqual(self.monitor.shelves.active(), {})
        self.assertEqual(self.monitor.snapshot()['unacknowledged_count'], 1)
        rows = self.journal.query()['items']
        self.assertEqual([row['status'] for row in rows], ['succeeded', 'rejected', 'succeeded', 'succeeded'])
        self.assertEqual(rows[1]['phase'], 'prepared')
        self.assertTrue(all((row['actor'], row['provider']) == ('admin', 'local') for row in rows))
        self.assertEqual(saved['operation_id'], rows[-1]['operation_id'])
        self.assert_no_acquisition()

    def test_anonymous_and_unprivileged_requests_cannot_mutate_or_dispatch(self):
        requests = self.browser(self.mutations())['requests']
        for name, status in ((None, 401), ('reader', 403)):
            if name: self.login(name)
            for request in requests:
                self.assertEqual(self.send(request).status_code, status)
        rows = self.journal.query()['items']
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(row['status'] == 'denied' and row['phase'] == 'prepared' for row in rows))
        self.assertEqual(self.queries.notes(self.identifier)['items'], [])
        self.assertEqual(self.monitor.shelves.active(), {})
        self.monitor.note.assert_not_called()
        self.monitor.shelves.begin.assert_not_called()
        self.monitor.shelves.restore.assert_not_called()
        self.assert_no_acquisition()

    def test_invalid_generated_fields_and_bounds_fail_before_activity_or_mutations(self):
        self.login('admin')
        mutations = [dict(action='note', id='1', comment=value) for value in ('', '  ', 'x' * 1001)]
        mutations += [dict(action='shelve', id='1', duration=value, reason='Reason') for value in ('59', '86401', '60.5', 'invalid')]
        mutations += [dict(action='restore', id='process_alarm', expected=value, reason='Reason') for value in ('', 'A' * 32, '0' * 31)]
        mutations += [dict(action='note', id=value, comment='Note') for value in ('0', '-1', '9223372036854775808')]
        mutations += [dict(action='restore', id='x' * 101, expected='0' * 32, reason='Reason')]
        for request in self.browser(mutations)['requests']:
            with self.subTest(request=request): self.assertEqual(self.send(request).status_code, 422)
        # Attribution is server-owned; fabricated fields are rejected by strict models.
        for request in self.browser(self.mutations())['requests']:
            request['body']['actor'] = 'forged'
            self.assertEqual(self.send(request).status_code, 422)
        self.assertEqual(self.journal.query()['items'], [])
        self.monitor.note.assert_not_called()
        self.monitor.shelves.begin.assert_not_called()
        self.monitor.shelves.restore.assert_not_called()
        self.assert_no_acquisition()

    def test_helpers_preserve_receipts_errors_and_encode_shelf_identifiers(self):
        mutations = [dict(action='restore', id='设备 +?%', expected='0' * 32, reason='Reason')]
        result = self.browser(mutations)
        self.assertEqual(result['requests'][0]['path'], '/api/alarms/shelves/%E8%AE%BE%E5%A4%87%20%2B%3F%25/restore')
        self.assertEqual((result['results'][0]['operation_id'], result['results'][0]['audit_status']), ('b' * 32, 'pending'))
        for status in (401, 403, 409, 422, 503):
            reply = self.browser(self.mutations(), status=status)
            self.assertEqual(len(reply['requests']), 3)  # No automatic replay.
            for error in reply['results']:
                self.assertEqual(error, dict(error='Synthetic denial', status=status, operation_id='b' * 32, audit_status='denied'))


if __name__ == '__main__':
    unittest.main()
