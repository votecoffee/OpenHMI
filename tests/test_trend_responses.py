"""SQL history/capture responses checked by the production browser validators."""
from copy import deepcopy
from types import SimpleNamespace
from threading import RLock
from unittest.mock import Mock
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openhmi.historian import Historian
from openhmi.history_routes import add_history_routes
from openhmi.projects import ProjectStore, Project, default_project
from openhmi.trend_recording import TrendRecorder
from openhmi.trend_routes import add_trend_routes
from tests.test_frontend_contract import frontend


class TrendResponseContractTests(unittest.TestCase):
    def store(self):
        store = ProjectStore()
        self.addCleanup(store.close)
        return store

    def test_sampled_sql_history_context_quality_and_truncation(self):
        driver = Mock()
        historian = Historian(self.store(), driver)
        tags = ['设备 Level', 'Running', 'Text']
        historian.configure({'tags': [dict(tag=tag, sample_ms=100, deadband=0, mode='change')
                                     for tag in tags], 'retention_days': 30, 'max_rows': 1000})
        for index, quality in enumerate(('good', 'bad', 'pending', 'stale', 'good')):
            driver.sample_snapshot.return_value = {
                tag: {'value': value, 'quality': quality, 'timestamp': None}
                for tag, value in zip(tags, (12.5 + index, bool(index % 2), '001,设备'))}
            historian.sample(index, 100 + index)
        app = FastAPI()
        add_history_routes(app, historian, 'a' * 32)
        with TestClient(app) as client:
            def query(**params):
                response = client.get('/api/history', params={'tags': ','.join(tags),
                    'end': 104, 'seconds': 3, 'trend_context': 'true', **params})
                self.assertEqual(response.status_code, 200, response.text)
                return response.json()
            history = query()
            truncated = query(limit=2)
            empty = query(tags='missing')
            negative_start = query(seconds=105)
        self.assertEqual({row['quality'] for row in history['samples']}, {'bad', 'pending', 'stale', 'good'})
        self.assertEqual(history['change_context'][tags[0]]['previous']['epoch'], 100)
        self.assertEqual(history['change_context']['Text']['previous']['value'], '001,设备')
        self.assertTrue(truncated['truncated'])
        self.assertIsNone(truncated['change_context'][tags[0]]['previous'])
        self.assertEqual(empty['samples'], [])
        self.assertLess(negative_start['start'], 0)
        result = frontend('trend_responses', histories=[history, truncated, empty, negative_start], statuses=[])
        self.assertEqual(result['histories'], [True] * 4)
        self.assertEqual({call[0] for call in driver.mock_calls}, {'sample_snapshot'})

    def test_sql_capture_empty_running_rollover_stopped_and_restart(self):
        driver = SimpleNamespace(lock=RLock(), sources={}, plc_hold=False, trend_demands={},
                                 sample_snapshot=Mock(return_value={}))
        store = self.store()
        recorder = TrendRecorder(store, driver)
        project = default_project().model_dump()
        project['controls'].append({'id': 'capture', 'kind': 'trend', 'label': '设备 capture',
            'tags': ['TankLevel', 'MotorRunning'], 'series': {'TankLevel': {'decimals': 8,
                'minimum': -10, 'maximum': 100}},
            'recording': {'sample_ms': 100, 'max_samples': 10}})
        recorder.configure(Project.model_validate(project).model_dump())
        app = FastAPI()
        add_trend_routes(app, recorder, SimpleNamespace(require=Mock()))
        statuses, histories = [], []
        with TestClient(app) as client:
            statuses.append(client.get('/api/trends/capture').json())
            identifier = client.post('/api/trends/capture', json={'action': 'start'}).json()['id']
            statuses.append(client.get('/api/trends/capture').json())
            histories.append(client.get(f'/api/trend-captures/{identifier}?end=100&seconds=1').json())
            for index in range(13):
                quality = ('good', 'bad', 'pending', 'stale')[index % 4]
                driver.sample_snapshot.return_value = {
                    'TankLevel': {'value': 20.5, 'quality': quality, 'timestamp': None},
                    'MotorRunning': {'value': True, 'quality': 'good', 'timestamp': None}}
                recorder.sample(index, 100 + index)
            statuses.append(client.get('/api/trends/capture').json())
            histories.append(client.get(f'/api/trend-captures/{identifier}?end=112&seconds=20').json())
            response = client.post('/api/trends/capture', json={'action': 'stop', 'capture_id': identifier})
            self.assertEqual(response.status_code, 200, response.text)
            statuses.append(client.get('/api/trends/capture').json())
            histories.append(client.get(f'/api/trend-captures/{identifier}?seconds=2').json())
            client.post('/api/trends/capture', json={'action': 'start'})
        restarted = TrendRecorder(store, driver)
        statuses.append(restarted.listing('capture'))
        statuses.append(restarted.listing('missing'))
        self.assertEqual(statuses[1]['captures'][0]['retained'], 0)
        self.assertIsNone(statuses[1]['captures'][0]['first'])
        self.assertEqual(statuses[2]['captures'][0]['rolled_off'], 3)
        self.assertEqual(statuses[3]['captures'][0]['reason'], 'manual stop')
        self.assertEqual(statuses[4]['captures'][0]['reason'], 'interrupted')
        self.assertEqual(len(histories[1]['samples']), 20)
        self.assertEqual(histories[2]['end'], 112)
        result = frontend('trend_responses', histories=histories, statuses=statuses)
        self.assertEqual(result['histories'], [True] * len(histories))
        self.assertEqual(result['statuses'], [True] * len(statuses))

    def test_malformed_responses_and_legacy_optional_fields(self):
        row = {'tag': 'A', 'epoch': 1, 'value': None, 'quality': 'pending'}
        history = {'start': 0, 'end': 2, 'truncated': False, 'samples': [row]}
        context = {'hold_seconds': 61, 'previous': {**row, 'epoch': -1}}
        valid_history = [history, {**history, 'samples': [row, row]},
            {**history, 'change_context': {'A': context}},
            {**history, 'samples': [row, {**row, 'tag': 'B', 'epoch': 0}]}]
        invalid_history = [None, {}, *[{**history, field: value} for field, value in (
            ('samples', None), ('samples', [None]), ('truncated', 0), ('end', 0),
            ('samples', [{**row, 'epoch': 3}]), ('samples', [{**row, 'quality': 'unknown'}]),
            ('samples', [{**row, 'epoch': 2}, row]), ('change_context', None),
            ('change_context', {'A': {**context, 'hold_seconds': 0}}),
            ('change_context', {'A': {**context, 'previous': row}}))]]
        capture = {'id': 1, 'started': 0, 'stopped': None, 'first': None, 'last': None,
            'retained': 0, 'max_samples': 10, 'rolled_off': 0,
            'series': [{'tag': 'A', 'type': 'number'}]}
        status = {'enabled': True, 'captures': [capture]}
        valid_status = [status, {**status, 'captures': []},
            {**status, 'error': 'Storage unavailable', 'captures': [{**capture, 'reason': None}]}]
        invalid_status = [None, {}, {**status, 'captures': [capture, capture]},
            {**status, 'captures': [None]}, {**status, 'error': {}},
            *[{**status, 'captures': [{**deepcopy(capture), key: value}]} for key, value in (
                ('id', 2**53), ('retained', 11), ('max_samples', 0), ('rolled_off', -1),
                ('first', 'bad'), ('series', [{'tag': 'A', 'type': 'string'}]),
                ('series', [{'tag': 'A', 'type': 'number', 'decimals': 9}]))]]
        result = frontend('trend_responses', histories=valid_history + invalid_history,
                          statuses=valid_status + invalid_status)
        self.assertEqual(result['histories'], [True] * len(valid_history) + [False] * len(invalid_history))
        self.assertEqual(result['statuses'], [True] * len(valid_status) + [False] * len(invalid_status))


if __name__ == '__main__':
    unittest.main()
