"""Deterministic runtime fault injection with no external equipment."""

import sqlite3
from threading import Event
import time
import unittest
from unittest.mock import Mock

from fastapi.testclient import TestClient

from openhmi.historian import Historian
from openhmi.logix import RuntimeDriver
from openhmi.projects import ProjectStore
from openhmi.server import create_app


class RuntimeWorkerTests(unittest.TestCase):
    def test_blocked_alarm_and_failed_history_do_not_stop_other_workers(self):
        app = create_app()
        monitor, historian = app.state.alarms, app.state.historian
        blocked, release, fail_history = Event(), Event(), Event()
        acquire, identity = Event(), Event()
        first_alarm = True
        original_alarm = monitor.sample

        def alarm():
            nonlocal first_alarm
            if first_alarm:
                first_alarm = False
                return original_alarm()
            blocked.set()
            if not release.wait(20):
                raise RuntimeError('Test did not release the alarm')
            return original_alarm()

        def history():
            if fail_history.is_set():
                raise sqlite3.OperationalError('Private fault injection marker')
        monitor.sample = alarm
        historian.sample = history
        app.state.driver.poll = lambda **_: acquire.set()
        app.state.identity_publisher.poll = identity.set

        def until(client, predicate, timeout=5):
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                response = client.get('/api/diagnostics')
                self.assertEqual(response.status_code, 200, response.text)
                workers = {item['id']: item for item in response.json()['workers']}
                if predicate(workers):
                    return workers
                time.sleep(0.02)
            self.fail(f'Worker states did not reach the expected condition: {workers}')

        with self.assertLogs(level='ERROR') as logs, TestClient(app) as client:
            try:
                self.assertTrue(blocked.wait(5))
                acquire.clear()
                identity.clear()
                fail_history.set()
                workers = until(client, lambda states: states['historian']['state'] == 'retrying')
                self.assertTrue(acquire.wait(2))
                self.assertTrue(identity.wait(2))
                self.assertEqual(workers['historian']['last_error_type'], 'OperationalError')
                self.assertIsNotNone(workers['alarms']['running_seconds'])
                self.assertEqual(client.get('/api/tags').status_code, 200)
                self.assertNotIn('Private fault injection marker', client.get('/api/diagnostics.json').text)

                overdue = until(client, lambda states: states['alarms']['state'] == 'overdue', timeout=8)
                self.assertGreaterEqual(overdue['alarms']['running_seconds'], 5)
                fail_history.clear()
                release.set()
                workers = until(client, lambda states: all(
                    states[name]['state'] == 'healthy' for name in ('historian', 'alarms', 'trends', 'identity')
                ))
                self.assertEqual(workers['historian']['consecutive_failures'], 0)
                self.assertGreaterEqual(workers['historian']['failures'], 1)
                self.assertIsNotNone(workers['historian']['last_success_at'])
            finally:
                release.set()
        self.assertTrue(any('Runtime worker historian failed' in line for line in logs.output))
        self.assertTrue(all(item['state'] == 'stopped' for item in app.state.runtime_workers.snapshot()))

    def test_shutdown_finishes_other_cleanup_after_one_failure(self):
        app = create_app()
        app.state.trends.shutdown = Mock(side_effect=RuntimeError('Synthetic cleanup error'))
        app.state.driver.close = Mock(wraps=app.state.driver.close)
        app.state.store.close = Mock(wraps=app.state.store.close)
        with self.assertLogs(level='ERROR') as logs, TestClient(app) as client:
            self.assertEqual(client.get('/api/tags').status_code, 200)
        app.state.driver.close.assert_called_once()
        app.state.store.close.assert_called_once()
        self.assertTrue(any('Runtime cleanup failed for trends' in line for line in logs.output))

    def test_historian_retries_a_due_sample_after_read_only_storage_recovers(self):
        store = ProjectStore()
        self.addCleanup(store.close)
        historian = Historian(store, RuntimeDriver())
        historian.configure({'tags': [{'tag': 'TankLevel', 'sample_ms': 10000, 'deadband': 0}],
                             'retention_days': 1, 'max_rows': 1000})
        with store._lock:
            store._db.execute('PRAGMA query_only=ON')
        with self.assertRaises(sqlite3.OperationalError):
            historian.sample(now=1, wall=100)
        with store._lock:
            store._db.execute('PRAGMA query_only=OFF')
        historian.sample(now=2, wall=101)
        samples = historian.query(['TankLevel'], 100, 102)['samples']
        self.assertEqual([(sample['epoch'], sample['value']) for sample in samples], [(101, 42)])
