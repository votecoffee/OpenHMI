"""SQL alarm lifecycle snapshots accepted by the production live-banner guard."""
from copy import deepcopy
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openhmi.alarm_ack_routes import add_alarm_ack_routes
from openhmi.alarms import AlarmMonitor
from openhmi.project_models import AlarmDefinition, Project, RevisionRequest, SaveRequest
from openhmi.projects import ProjectStore
from tests.test_frontend_contract import frontend


class AlarmSnapshotContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = frontend('alarm_snapshots', snapshots=[])['path']

    def fixture(self):
        store = ProjectStore()
        self.addCleanup(store.close)
        values = {'ProcessAlarm': False}
        source = Mock(side_effect=lambda: values.copy())
        monitor = AlarmMonitor(store, source)
        app = FastAPI()
        add_alarm_ack_routes(app, monitor, Mock(), Mock(), store)
        return store, values, source, monitor, TestClient(app)

    def apply(self, store, project):
        state = store.snapshot()
        saved = store.save(SaveRequest(expected_revision=state['draft_revision'], project=project))
        return store.apply(RevisionRequest(expected_revision=saved['draft_revision']))

    def test_real_snapshot_state_ack_shelf_quality_staleness_and_retirement(self):
        store, values, source, monitor, client = self.fixture()
        project = Project.model_validate(store.snapshot()['active'])
        project.alarms = [AlarmDefinition(id=f'fixture_{priority}', tag='ProcessAlarm', priority=priority,
            message=f'设备 alarm {priority}', response='1. Inspect sensor\n2. Restore normal condition')
            for priority in range(1, 5)]
        self.apply(store, project)
        snapshots = []
        def capture():
            calls = source.call_count
            response = client.get(self.path)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(source.call_count, calls, 'Snapshot reads cannot acquire new tag data')
            snapshots.append(response.json())
            return snapshots[-1]
        with client, patch('openhmi.alarms.monotonic', return_value=100):
            self.assertIsNone(capture()['sampled_revision'])
            monitor.sample()
            self.assertEqual(capture()['active_count'], 0)
            values['ProcessAlarm'] = True
            monitor.sample()
            raised = capture()
            self.assertEqual((raised['active_count'], raised['unacknowledged_count']), (4, 4))
            self.assertEqual({row['priority'] for row in raised['annunciated_outstanding']}, {1, 2, 3, 4})
            first = next(row for row in raised['outstanding'] if row['priority'] == 1)
            self.assertEqual(first['messages']['en'], '设备 alarm 1')
            self.assertIn('Inspect sensor', first['response'])
            monitor.shelves.begin(first['occurrence_id'], 60, 'Offline investigation', ('Fixture Operator', 'local'), '1' * 32)
            shelved = capture()
            self.assertEqual((shelved['active_count'], shelved['annunciated_active_count'], shelved['shelved_count']), (4, 3, 1))
            self.assertEqual(len(shelved['outstanding']), 4)
            monitor.shelves.restore(first['alarm_id'], '1' * 32, 'Offline restore', ('Fixture Operator', 'local'), '2' * 32)
            self.assertEqual(capture()['annunciated_active_count'], 4)
            values['ProcessAlarm'] = None
            monitor.sample()
            bad = capture()
            self.assertEqual({item['quality'] for item in bad['states'].values()}, {'bad'})
            self.assertEqual(bad['active_count'], 4)
            self.assertTrue(all(row['returned_at'] is None for row in bad['outstanding']))
            monitor.error = 'Synthetic evaluation fault'
            with patch('openhmi.alarms.monotonic', return_value=monitor._last_sample_monotonic + 6):
                stale = capture()
            self.assertTrue(stale['evaluation_stale'])
            self.assertEqual(stale['error'], 'Synthetic evaluation fault')
            values['ProcessAlarm'] = True
            monitor.sample()
            self.assertFalse(capture()['evaluation_stale'])
            monitor.acknowledge(first['occurrence_id'], identity=('Fixture Operator', 'local'))
            acknowledged = capture()
            self.assertEqual((acknowledged['active_count'], acknowledged['unacknowledged_count']), (4, 3))
            values['ProcessAlarm'] = False
            monitor.sample()
            returned = capture()
            self.assertEqual((returned['active_count'], returned['unacknowledged_count']), (0, 3))
            monitor.acknowledge()
            self.assertEqual(capture()['outstanding'], [])
            values['ProcessAlarm'] = True
            monitor.sample()
            capture()
            project.alarms = []
            self.apply(store, project)
            previous = capture()
            self.assertNotEqual(previous['sampled_revision'], store.snapshot()['active_revision'])
            monitor.sample()
            retired = capture()
            self.assertEqual((retired['active_count'], retired['unacknowledged_count']), (0, 4))
            self.assertTrue(all(row['retired_at'] for row in retired['outstanding']))
            monitor.acknowledge()
            self.assertEqual(capture()['annunciated_outstanding'], [])
            reopened = AlarmMonitor(store, source)
            snapshots.append(reopened.snapshot())
            self.assertEqual(snapshots[-1]['occurrences'], monitor.snapshot()['occurrences'])
        result = frontend('alarm_snapshots', snapshots=snapshots)
        self.assertEqual(result['path'], '/api/alarms')
        self.assertEqual(result['valid'], [True] * len(snapshots))

    def test_legacy_optional_fields_and_malformed_consumed_shapes(self):
        _, values, _, monitor, client = self.fixture()
        values['ProcessAlarm'] = True
        monitor.sample()
        with client:
            current = client.get(self.path).json()
        legacy = deepcopy(current)
        for key in ('annunciated_outstanding', 'annunciated_active_count', 'annunciated_unacknowledged_count',
                    'shelved_count', 'sampled_revision', 'evaluation_stale'):
            legacy.pop(key)
        valid = [current, legacy]
        invalid = [None, [], {}, *[{**deepcopy(current), key: value} for key, value in (
            ('active_count', -1), ('unacknowledged_count', '1'), ('shelved_count', True),
            ('sampled_revision', 2**53), ('evaluation_stale', 'false'), ('states', []),
            ('states', {'process_alarm': {'quality': 'pending'}}), ('outstanding', None),
            ('annunciated_outstanding', {}), ('annunciated_outstanding', [None]))]]
        for key, value in (('priority', 5), ('message', {}), ('occurrence_id', 2**53), ('messages', {'en': None})):
            invalid.append({**deepcopy(current), 'annunciated_outstanding': [{**current['outstanding'][0], key: value}]})
        invalid.append({**legacy, 'outstanding': [None]})
        self.assertEqual(frontend('alarm_snapshots', snapshots=valid + invalid)['valid'],
                         [True] * len(valid) + [False] * len(invalid))


if __name__ == '__main__':
    unittest.main()
