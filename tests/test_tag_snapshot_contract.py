"""Acquisition cache responses checked by the actual browser normalizer."""
from copy import deepcopy
from types import SimpleNamespace
from threading import RLock
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openhmi.acquisition_routes import add_acquisition_routes
from openhmi.logix import RuntimeDriver
from openhmi.project_models import Project
from tests.test_frontend_contract import frontend
from tests.test_logix_history import FakePLC, logix_project


class TagSnapshotContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.paths = frontend('tag_snapshots', snapshots=[])['paths']

    def test_real_cache_partial_fault_stale_recovery_and_status_only_responses(self):
        clients = []
        def factory(*args, **kwargs):
            client = FakePLC(*args, **kwargs)
            clients.append(client)
            return client
        driver = RuntimeDriver(factory)
        self.addCleanup(driver.close)
        project = logix_project()
        project['tags'].extend([
            {'name': 'Missing', 'connection': 'plc', 'address': 'NoSuchTag', 'type': 'number'},
            {'name': 'FixtureText', 'type': 'string', 'initial': '001,设备\nΔ'},
            {'name': 'FixtureZero', 'type': 'integer', 'initial': 0},
            {'name': 'FixtureOff', 'type': 'boolean', 'initial': False}])
        project['screens'][0]['controls'].append({'id': 'missing', 'kind': 'numeric', 'label': 'Missing', 'tag': 'Missing'})
        project = Project.model_validate(project).model_dump()
        app = FastAPI()
        add_acquisition_routes(app, SimpleNamespace(lock=RLock(), driver=driver), Mock())
        frames = []
        def capture(now, status_only=False):
            before = [(len(client.reads), len(client.writes)) for client in clients]
            with patch('openhmi.logix.time', SimpleNamespace(monotonic=lambda: now)), \
                 patch.object(driver, 'poll', side_effect=AssertionError('GET cannot poll')), \
                 patch.object(driver, 'lease', side_effect=AssertionError('GET cannot subscribe')):
                response = client.get(self.paths[int(status_only)])
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual([(len(client.reads), len(client.writes)) for client in clients], before)
            frames.append({'data': response.json(), 'statusOnly': status_only})
            return frames[-1]['data']
        with TestClient(app) as client:
            driver.plc_hold = True
            driver.configure(project)
            self.assertTrue(capture(1)['plc_hold'])
            self.assertEqual(clients, [])
            driver.plc_hold = False
            driver.configure(project)
            self.assertEqual(capture(1)['samples']['LevelA']['quality'], 'pending')
            driver.lease('snapshot-contract', ['fast', 'slow'], 1)
            driver.poll(1)
            fresh = capture(1)
            self.assertEqual(fresh['samples']['Missing']['quality'], 'bad')
            self.assertNotIn('Missing', fresh['values'])
            self.assertEqual(fresh['values']['LevelA'], 65)
            self.assertIs(fresh['values']['MotorA.Running'], True)
            self.assertEqual(fresh['values']['FixtureText'], '001,设备\nΔ')
            self.assertEqual(fresh['values']['FixtureZero'], 0)
            self.assertIs(fresh['values']['FixtureOff'], False)
            self.assertTrue(fresh['connections'][0]['connected'])
            with patch.object(driver, 'sample_snapshot', side_effect=AssertionError('Status-only cannot copy tag samples')):
                status = capture(1, True)
            self.assertNotIn('samples', status)
            self.assertNotIn('values', status)
            self.assertTrue(all('groups' not in route for route in status['connections']))
            stale = capture(100)
            self.assertEqual(stale['samples']['LevelA']['quality'], 'stale')
            self.assertNotIn('LevelA', stale['values'])
            self.assertTrue(stale['connections'][0]['data_unavailable'])
            driver.lease('snapshot-contract', ['fast', 'slow'], 101)
            driver.poll(101)
            self.assertEqual(capture(101)['samples']['LevelA']['quality'], 'good')
            project['connections'][0]['enabled'] = False
            driver.configure(project)
            self.assertNotIn('LevelA', capture(102)['values'])
        result = frontend('tag_snapshots', snapshots=frames)
        self.assertEqual(result['paths'], ['/api/tags', '/api/tags?status_only=true'])
        self.assertTrue(all(item['valid'] for item in result['results']))
        normalized = result['results'][3]['normalized']
        self.assertEqual((normalized['values'], normalized['samples'], normalized['plcHold']), ({}, {}, False))
        for frame, item in zip(frames, result['results']):
            if not frame['statusOnly']:
                self.assertEqual(item['normalized']['values'], frame['data']['values'])
                self.assertEqual(item['normalized']['samples'], frame['data']['samples'])
            self.assertEqual(item['normalized']['connections'], frame['data']['connections'])
        self.assertTrue(all(not client.writes for client in clients))

    def test_legacy_defaults_per_tag_faults_and_malformed_top_level_fields(self):
        values = {'Zero': 0, 'Off': False, 'Text': '001,设备', 'UDT': {'Running': True, 'Points': [1, 2]}}
        complete = {'values': values, 'samples': {'Zero': {'quality': 'good'}, 'Off': None,
                    'Text': {'quality': 'stale', 'error': {'reason': 'Offline fixture'}}},
                    'connections': [{'id': 'plc', 'connected': True}], 'plc_hold': False}
        valid = [{'data': complete}, {'data': {'values': values}},
                 {'data': {'connections': [], 'plc_hold': True}, 'statusOnly': True}]
        invalid = [None, [], {}, *[{**deepcopy(complete), key: value} for key, value in (
            ('values', None), ('values', []), ('samples', []), ('samples', None),
            ('connections', None), ('connections', [None]), ('connections', [{'id': 1, 'connected': True}]),
            ('connections', [{'id': 'plc', 'connected': 'true'}]), ('plc_hold', 0))]]
        frames = valid + [{'data': item} for item in invalid] + [
            {'data': {}, 'statusOnly': True}, {'data': {'connections': []}, 'statusOnly': True},
            {'data': {'plc_hold': False}, 'statusOnly': True}]
        result = frontend('tag_snapshots', snapshots=frames)['results']
        self.assertEqual([item['valid'] for item in result], [True] * len(valid) + [False] * (len(frames) - len(valid)))
        self.assertEqual(result[0]['normalized']['values'], values)
        self.assertEqual(result[0]['normalized']['samples'], complete['samples'])
        self.assertEqual(result[1]['normalized'], {'values': values, 'samples': {}, 'connections': [], 'plcHold': False})
        self.assertTrue(all(item['error'] == 'Invalid tag status response' for item in result[len(valid):]))


if __name__ == '__main__':
    unittest.main()
