"""Production history/capture queries bound through their actual HTTP registrars."""
import csv
from io import StringIO
import json
from threading import BoundedSemaphore
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI
from fastapi.responses import Response
from fastapi.testclient import TestClient
from openhmi.history_routes import add_history_routes
from openhmi.trend_routes import add_trend_routes
from openhmi.historian import Historian
from openhmi.projects import ProjectStore
from tests.test_frontend_contract import frontend


class HistoryQueryContractTests(unittest.TestCase):
    def router(self):
        def query(tags, start, end, limit, trend_context=False):
            return {'tags': tags, 'start': start, 'end': end, 'limit': limit,
                    'trend_context': trend_context, 'truncated': False, 'samples': [
                        {'tag': tags[0], 'timestamp': '2026-01-01T00:00:00+00:00',
                         'value': '001,设备', 'quality': 'good', 'source_timestamp': None}]}
        def batches(tags, start, end):
            for tag in tags:
                yield tag, [(start + 0.5, 1, json.dumps('001,设备'), 'good', None)]
        historian = SimpleNamespace(query=Mock(side_effect=query),
            recorded_tags=Mock(side_effect=lambda prefix, after, limit: {'prefix': prefix, 'after': after, 'limit': limit}),
            export_batches=Mock(side_effect=batches), export_slot=BoundedSemaphore(1))
        recorder = SimpleNamespace(
            history=Mock(side_effect=lambda identifier, seconds, end: {'id': identifier, 'seconds': seconds, 'end': end}),
            csv=Mock(return_value=Response('capture\n', media_type='text/csv')))
        app = FastAPI()
        add_history_routes(app, historian, 'a' * 32)
        add_trend_routes(app, recorder, SimpleNamespace(require=Mock()))
        return TestClient(app), historian, recorder

    def test_actual_browser_windows_search_and_exports_bind_to_routers(self):
        payload = frontend('history_queries')
        self.assertEqual(payload['empty'], {'query': '', 'csv': ''})
        self.assertEqual(len(payload['requests']), 11)
        client, historian, recorder = self.router()
        with client:
            for request in payload['requests']:
                with self.subTest(path=request['path']):
                    self.assertEqual(request.get('method', 'GET'), 'GET')
                    self.assertNotIn('body', request)
                    reply = client.get(request['path'], headers=request.get('headers', {}))
                    self.assertEqual(reply.status_code, 200, reply.text)
                    url = urlsplit(request['path'])
                    params = parse_qs(url.query, keep_blank_values=True)
                    if url.path == '/api/history':
                        data = reply.json()
                        self.assertEqual(data['tags'], list(dict.fromkeys(params['tags'][0].split(','))))
                        self.assertEqual(data['end'] - data['start'], int(params['seconds'][0]))
                        if 'end' in params: self.assertEqual(data['end'], float(params['end'][0]))
                        self.assertEqual(data['limit'], int(params.get('limit', ['2000'])[0]))
                        self.assertTrue(data['trend_context'])
                    elif url.path == '/api/history/tags':
                        self.assertEqual(reply.json(), {'prefix': params.get('prefix', [''])[0],
                            'after': params.get('after', [None])[0], 'limit': int(params.get('limit', ['50'])[0])})
                    elif url.path.startswith('/api/history'):
                        rows = list(csv.reader(StringIO(reply.text)))
                        self.assertEqual(rows[0], ['tag', 'timestamp', 'value', 'quality', 'source_timestamp'])
                        self.assertEqual(rows[1][2], '001,设备')
                        self.assertIn('tag-history.csv', reply.headers['content-disposition'])
                        if url.path == '/api/history.csv':
                            self.assertEqual(reply.headers['x-openhmi-truncated'], 'false')
                            call = historian.query.call_args.args
                            self.assertEqual(call[1], float(params['end'][0]) - int(params['seconds'][0]))
                            self.assertEqual(call[2], float(params['end'][0]))
                            self.assertEqual(call[3], 20000)
                            self.assertTrue(request['timed'])
                            self.assertNotIn('headers', request)
                        else:
                            historian.export_batches.assert_called_with(['设备 A', 'Motor.Speed'], 0.0, 31536000.0)
                            self.assertTrue(historian.export_slot.acquire(blocking=False))
                            historian.export_slot.release()
                    elif url.path.endswith('/csv'):
                        self.assertEqual(reply.text, 'capture\n')
                    else:
                        self.assertEqual(reply.json(), {'id': 9223372036854775807, 'seconds': 10, 'end': 1700000000.125})
                    if url.path not in ('/api/history.csv',):
                        self.assertEqual(request['headers']['X-OpenHMI-Project'], 'a' * 32)
        recorder.csv.assert_called_once_with(123)
        recorder.history.assert_called_once_with(9223372036854775807, 10, 1700000000.125)
        self.assertNotIn('trend_context', payload['requests'][5]['path'])

    def test_actual_recorded_pages_and_malformed_replies_use_browser_validator(self):
        store = ProjectStore()
        self.addCleanup(store.close)
        historian = Historian(store, None)
        with store.transaction() as db:
            for tag in ('A', 'B', '设备 A'):
                db.execute('INSERT INTO tag_history(tag,timestamp,value,quality) VALUES(?,?,?,?)',
                           (tag, 1700000000.125, '1', 'good'))
        first = historian.recorded_tags('', None, 2)
        second = historian.recorded_tags('', first['next_after'], 2)
        prefix = historian.recorded_tags('设备', None, 2)
        empty = historian.recorded_tags('missing', None, 2)
        row = {'tag': 'A', 'latest': '2026-01-01T00:00:00+00:00'}
        valid = [first, second, prefix, empty]
        invalid = [None, {}, {'next_after': None}, {'items': []},
                   {'items': [], 'next_after': 'A'}, {'items': [row], 'next_after': 42},
                   {'items': [row], 'next_after': 'B'}, {'items': [row, row], 'next_after': None},
                   {'items': [{'tag': 'A', 'latest': 'bad date'}], 'next_after': None},
                   {'items': [{'tag': '', 'latest': row['latest']}], 'next_after': None}]
        self.assertEqual(frontend('recorded_pages', pages=valid + invalid),
                         [True] * len(valid) + [False] * len(invalid))

    def test_invalid_windows_limits_and_stale_project_guards_prevent_reads(self):
        client, historian, recorder = self.router()
        invalid = [
            '/api/history?tags=A&seconds=0', '/api/history?tags=A&seconds=31536001',
            '/api/history?tags=A&limit=0', '/api/history?tags=A&limit=20001',
            '/api/history?tags=A&end=nan', '/api/history?tags=A&end=-1',
            '/api/history?tags=' + ','.join('T' + str(i) for i in range(13)),
            '/api/history?tags=' + 'x' * 201,
            '/api/history.csv?tags=A&start=100&end=100',
            '/api/history/full.csv?tags=A&start=0&end=31536001',
            '/api/history/tags?prefix=A&after=B', '/api/history/tags?limit=101',
            '/api/history/tags?prefix=' + 'x' * 201,
            '/api/trend-captures/0', '/api/trend-captures/9223372036854775808/csv',
            '/api/trend-captures/1?seconds=604801', '/api/trend-captures/1?end=-1',
            '/api/trend-captures/1?end=32503680001',
        ]
        with client:
            for path in invalid:
                with self.subTest(path=path): self.assertEqual(client.get(path).status_code, 422)
            for path in ('/api/history/tags?project_instance=' + 'b' * 32,
                         '/api/history/full.csv?tags=A&project_instance=' + 'b' * 32):
                self.assertEqual(client.get(path).status_code, 409)
        historian.query.assert_not_called()
        historian.recorded_tags.assert_not_called()
        historian.export_batches.assert_not_called()
        recorder.history.assert_not_called()
        recorder.csv.assert_not_called()
        self.assertTrue(historian.export_slot.acquire(blocking=False))
        historian.export_slot.release()


if __name__ == '__main__':
    unittest.main()
