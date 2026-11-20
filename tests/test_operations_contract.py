"""Production activity/diagnostics requests bound through the real registrar."""
import csv
from io import StringIO
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import ANY, Mock
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from openhmi.activity import ActivityJournal, STATUSES
from openhmi.operations_routes import add_operations_routes
from openhmi.projects import ProjectStore
from tests.test_frontend_contract import frontend


class OperationsQueryContractTests(unittest.TestCase):
    def router(self):
        store = ProjectStore()
        self.addCleanup(store.close)
        principal = SimpleNamespace(name='设备 Operator', provider='local', groups={'Operators'}, permissions=set())
        security = SimpleNamespace(user=Mock(return_value=principal), configured=lambda: True, require=Mock())
        journal = ActivityJournal(store, security)
        request = Request({'type': 'http', 'headers': []})
        for status in sorted(STATUSES):
            ticket = journal.start(request, 'offline_fixture', '设备 A,+%=x', {})
            if status != 'pending': journal.finish(ticket.id, status, {}, '@Review,设备')
        journal.query = Mock(wraps=journal.query)
        driver = SimpleNamespace(lock=RLock(), sources={}, definitions={}, project={'connections': []}, plc_hold=False,
            sample_snapshot=Mock(return_value={
                '设备 A,+%=x': {'quality': 'bad', 'value_type': 'number', 'error': 'Offline fixture'},
                'Good': {'quality': 'good', 'value_type': 'number'},
                'Pending': {'quality': 'pending', 'value_type': 'boolean'}}), status=Mock(return_value=[]))
        workers = SimpleNamespace(snapshot=Mock(return_value=[]))
        app = FastAPI()
        app.state.project_instance = 'a' * 32
        add_operations_routes(app, journal, security, driver, workers)
        return TestClient(app), journal, security, driver, workers

    def test_actual_queries_and_exports_preserve_filters_utc_cursors_and_defaults(self):
        activity = [{}, {'filters': {'actor': '设备 Operator', 'search': '设备 A,+%=x',
            'start': '2026-01-01T05:30:00+05:30', 'end': '2026-12-31T23:59:59Z'},
            'before': '9223372036854775807', 'options': {'limit': 1}},
            {'options': {'limit': 1000}}, *[{'filters': {'status': status}} for status in sorted(STATUSES)]]
        diagnostics = [{}, {'criteria': {'search': '设备 A,+%=x', 'quality': 'bad', 'connection': ':local'},
                            'offset': 0, 'options': {'limit': 1}},
                       {'criteria': {'search': '', 'quality': 'non-good', 'connection': ''},
                        'offset': 1, 'options': {'limit': 1000}}, {'offset': 100000}]
        payload = frontend('operations_queries', activity=activity, diagnostics=diagnostics)
        self.assertEqual(set(payload['outcomes']), STATUSES)
        self.assertEqual(payload['requests'][0]['path'], '/api/activity?')
        self.assertEqual(payload['csv'][0], '/api/activity.csv?')
        self.assertEqual(payload['exports'][0], '/api/diagnostics.json?')
        self.assertIn('start=2026-01-01T00%3A00%3A00.000Z', payload['requests'][1]['path'])
        client, journal, security, driver, workers = self.router()
        with client:
            for item in payload['requests']:
                self.assertEqual(item.get('method', 'GET'), 'GET')
                self.assertNotIn('body', item)
                self.assertEqual(item['headers'], {'X-OpenHMI-Project': 'a' * 32})
                self.assertTrue(item['timed'])
                response = client.get(item['path'], headers=item['headers'])
                self.assertEqual(response.status_code, 200, response.text)
                params = parse_qs(urlsplit(item['path']).query, keep_blank_values=True)
                if urlsplit(item['path']).path == '/api/activity':
                    expected = (int(params.get('limit', ['100'])[0]),
                        int(params['before_id'][0]) if 'before_id' in params else None,
                        *[params.get(key, [''])[0] for key in ('actor', 'status', 'search')],
                        *[params.get(key, [None])[0] for key in ('start', 'end')])
                    self.assertEqual(journal.query.call_args.args, expected)
                    security.require.assert_called_with(ANY, 'activity.view')
                else:
                    data = response.json()
                    self.assertEqual(data['offset'], int(params.get('offset', ['0'])[0]))
                    if params.get('quality') == ['bad']:
                        self.assertEqual([tag['name'] for tag in data['tags']], ['设备 A,+%=x'])
                        self.assertEqual(data['tags'][0]['connection'], '')
                    if params.get('quality') == ['non-good']:
                        self.assertEqual(data['total_tags'], 2)
                    security.require.assert_called_with(ANY, 'diagnostics.view')
                    driver.sample_snapshot.assert_called_with(ANY, include_values=False)
            for path in payload['csv']:
                reply = client.get(path)
                self.assertEqual(reply.status_code, 200, reply.text)
                self.assertEqual(journal.query.call_args.args[:2], (20000, None))
                self.assertIn('operator-activity.csv', reply.headers['content-disposition'])
                self.assertIn(reply.headers['x-openhmi-truncated'], ('true', 'false'))
            rows = list(csv.DictReader(StringIO(client.get(payload['csv'][0]).text)))
            self.assertEqual(rows[0]['actor'], '设备 Operator')
            self.assertIn("'@Review,设备", {row['error'] for row in rows})
            for path in payload['exports']:
                reply = client.get(path)
                self.assertEqual(reply.status_code, 200, reply.text)
                self.assertIn('runtime-diagnostics.json', reply.headers['content-disposition'])
                data = reply.json()
                self.assertEqual(data['offset'], 0)
                self.assertEqual(data['capture']['project_instance'], 'a' * 32)
                self.assertTrue(all('value' not in row for row in data['tags']))
        self.assertTrue(workers.snapshot.called)

    def test_invalid_generated_bounds_are_rejected_before_data_reads(self):
        activity = [{'options': {'limit': limit}} for limit in (0, 1001)] + [
            {'before': value} for value in ('-1', '9223372036854775808', '1.5')] + [
            {'filters': {key: value}} for key, value in (
                ('status', 'unknown'), ('actor', 'x' * 201), ('search', 'x' * 101))]
        diagnostics = [{'offset': value} for value in (-1, 100001, '1.5')] + [
            {'options': {'limit': limit}} for limit in (0, 1001)] + [
            {'criteria': {key: value}} for key, value in (
                ('quality', 'unknown'), ('search', 'x' * 101), ('connection', 'x' * 61))]
        payload = frontend('operations_queries', activity=activity, diagnostics=diagnostics)
        client, journal, _, driver, workers = self.router()
        with client:
            for request in payload['requests']:
                with self.subTest(path=request['path']):
                    self.assertEqual(client.get(request['path']).status_code, 422)
            journal.query.assert_not_called()
            driver.sample_snapshot.assert_not_called()
            workers.snapshot.assert_not_called()
            for value in ('bad-date', '2026-01-01T00:00:00'):
                reply = client.get('/api/activity', params={'start': value})
                self.assertEqual(reply.status_code, 422, reply.text)

    def test_denial_stops_all_read_and_export_paths_before_service_calls(self):
        client, journal, security, driver, workers = self.router()
        security.require.side_effect = HTTPException(403, 'Synthetic denial')
        with client:
            for path in ('/api/activity', '/api/activity.csv', '/api/diagnostics', '/api/diagnostics.json'):
                self.assertEqual(client.get(path).status_code, 403)
        journal.query.assert_not_called()
        driver.sample_snapshot.assert_not_called()
        driver.status.assert_not_called()
        workers.snapshot.assert_not_called()


if __name__ == '__main__':
    unittest.main()
