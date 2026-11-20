"""Real journal and runtime projections checked by production JS validators."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import time
import unittest

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from openhmi.activity import ActivityJournal, STATUSES
from openhmi.logix import RuntimeDriver
from openhmi.operations_routes import add_operations_routes
from openhmi.projects import ProjectStore
from openhmi.runtime_workers import RuntimeWorkers
from tests.test_frontend_contract import frontend
from tests.test_logix_history import FakePLC, logix_project


class OperationsResponseContractTests(unittest.TestCase):
    def services(self):
        store = ProjectStore()
        self.addCleanup(store.close)
        principal = SimpleNamespace(name='设备 Operator', provider='local', groups={'Operators'}, permissions=set())
        security = SimpleNamespace(user=Mock(return_value=principal), configured=lambda: True, require=Mock())
        journal = ActivityJournal(store, security)
        driver = RuntimeDriver(FakePLC)
        self.addCleanup(driver.close)
        workers = RuntimeWorkers({'acquisition': (0.1, Mock()), 'historian': (1, Mock())})
        app = FastAPI()
        app.state.project_instance = 'a' * 32
        add_operations_routes(app, journal, security, driver, workers)
        return store, journal, driver, workers, TestClient(app)

    def test_sql_activity_states_filtered_pages_and_restart(self):
        store, journal, driver, _, client = self.services()
        request = Request({'type': 'http', 'headers': [], 'client': ('offline', 0)})
        for status in sorted(STATUSES):
            ticket = journal.start(request, 'offline_fixture', '设备 A', {
                'tag': 'TankLevel', 'before': {'value': 12.5, 'quality': 'good', 'timestamp': None}})
            if status != 'pending':
                journal.finish(ticket.id, status, {'verification': 'offline', 'count': 0},
                               None if status == 'succeeded' else 'Synthetic outcome')
        dispatched = journal.start(request, 'offline_fixture', 'prepared for recovery', {})
        dispatched.dispatch()  # Durable journal marker only; no equipment callback.
        pages = []
        with client:
            cursor = None
            while True:
                response = client.get('/api/activity', params={'limit': 2, **({'before_id': cursor} if cursor else {})})
                self.assertEqual(response.status_code, 200, response.text)
                page = response.json()
                pages.append(page)
                if not page['has_more']: break
                cursor = page['next_before_id']
            for status in sorted(STATUSES):
                page = client.get('/api/activity', params={'status': status, 'actor': '设备 Operator'}).json()
                self.assertTrue(page['items'])
                pages.append(page)
            pages.append(client.get('/api/activity?search=missing').json())
        restarted = ActivityJournal(store, journal.security)
        restart_page = restarted.query()
        pages.append(restart_page)
        self.assertFalse(any(row['status'] == 'pending' for row in restart_page['items']))
        self.assertEqual(restart_page['items'][0]['status'], 'uncertain')
        self.assertIn('interrupted', {row['status'] for row in restart_page['items']})
        result = frontend('operations_responses', pages=pages, snapshots=[])
        self.assertEqual(set(result['outcomes']), STATUSES)
        self.assertEqual(result['pages'], [True] * len(pages))
        self.assertFalse(driver.connections)

    def test_actual_diagnostics_pages_worker_health_and_value_free_export(self):
        _, _, driver, workers, client = self.services()
        driver.plc_hold = True
        project = logix_project()
        driver.configure(project)
        snapshots = []
        with client, patch.object(driver, 'lease', side_effect=AssertionError('Diagnostics cannot subscribe')):
            for params in ({'limit': 1}, {'limit': 1, 'offset': 1}, {'offset': 100},
                           {'search': 'missing'}, {'quality': 'bad', 'connection': 'plc'}):
                reply = client.get('/api/diagnostics', params=params)
                self.assertEqual(reply.status_code, 200, reply.text)
                snapshots.append({'data': reply.json(), 'offset': params.get('offset', 0)})
            self.assertEqual(snapshots[0]['data']['connections'][0]['state'], 'held')
            self.assertFalse(driver.connections)
            project['connections'][0]['enabled'] = False
            driver.configure(project)
            snapshots.append({'data': client.get('/api/diagnostics').json(), 'offset': 0})
            self.assertEqual(snapshots[-1]['data']['connections'][0]['state'], 'disabled')
            driver.plc_hold = False
            driver.configure(logix_project())
        driver.lease('offline-contract', ['fast', 'slow'])
        driver.poll()
        with workers.lock:
            workers.health['acquisition'].update(_running_since=time.monotonic() - 6)
            workers.health['historian'].update(state='retrying', failures=1, last_error_type='Synthetic',
                                               _retry_at=time.monotonic() + 1)
        with client, patch.object(driver, 'lease', side_effect=AssertionError('Diagnostics cannot subscribe')):
            response = client.get('/api/diagnostics.json')
            self.assertEqual(response.status_code, 200, response.text)
            exported = response.json()
            snapshots.append({'data': exported, 'offset': 0})
            self.assertEqual(exported['capture']['project_instance'], 'a' * 32)
            self.assertEqual({item['state'] for item in exported['workers']}, {'overdue', 'retrying'})
            self.assertTrue(exported['connections'][0]['timings'])
            self.assertTrue(all('value' not in tag for tag in exported['tags']))
        result = frontend('operations_responses', pages=[], snapshots=snapshots)
        self.assertEqual(result['snapshots'], [True] * len(snapshots))
        self.assertFalse(driver.connections['plc'].client.writes)

    def test_malformed_paging_and_legacy_nullable_metadata(self):
        _, journal, _, _, client = self.services()
        request = Request({'type': 'http', 'headers': []})
        for _ in range(3): journal.start(request, 'offline_fixture', 'test', {})
        page = journal.query(limit=2)
        valid_pages = [page, journal.query(before_id=page['next_before_id']), journal.query(search='missing')]
        invalid_pages = [None, {}, {**page, 'next_before_id': 1},
            {**page, 'items': list(reversed(page['items']))}, {**page, 'items': [page['items'][0]] * 2},
            {**page, 'items': [{**row, 'operation_id': 'duplicate'} for row in page['items']]},
            {**page, 'items': [{**page['items'][0], 'id': 2**53}]},
            {**page, 'pending_finalizations': -1}, {**page, 'items': []}]
        oversized = [{**page['items'][0], 'id': value, 'operation_id': f'offline-{value}'}
                     for value in range(1001, 0, -1)]
        invalid_pages.append({**page, 'items': oversized, 'has_more': False, 'next_before_id': None})
        with client:
            snapshot = client.get('/api/diagnostics').json()
        valid_snapshots = [{'data': snapshot, 'offset': 0}]
        malformed = [None, {}, {**snapshot, 'tags': [None]},
            {**snapshot, 'next_offset': 1, 'truncated': True}, {**snapshot, 'truncated': True},
            {**snapshot, 'tags': [snapshot['tags'][0]] * len(snapshot['tags'])},
            {**snapshot, 'connections': [{'id': 'plc', 'name': 'Offline', 'path': 'offline', 'state': 'scan overdue',
                'scan_age_seconds': {}, 'read_calls': 0, 'tags_read': 0, 'route_failures': 0, 'groups': [], 'timings': {}}]}]
        result = frontend('operations_responses', pages=valid_pages + invalid_pages,
                          snapshots=valid_snapshots + [{'data': item, 'offset': 0} for item in malformed])
        self.assertEqual(result['pages'], [True] * len(valid_pages) + [False] * len(invalid_pages))
        self.assertEqual(result['snapshots'], [True] + [False] * len(malformed))


if __name__ == '__main__':
    unittest.main()
