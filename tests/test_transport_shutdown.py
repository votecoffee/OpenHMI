"""Bounded offline shutdown checks; no controller connections or writes."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Event
import unittest
from unittest.mock import Mock, patch

from openhmi.logix import RuntimeDriver
from tests.test_logix_history import FakePLC, logix_project


class TransportShutdownTests(unittest.TestCase):
    def fixture(self):
        project = logix_project()
        project['connections'] += [{**project['connections'][0], 'id': name, 'path': name + '-offline/0'}
                                  for name in ('other', 'last')]
        driver = RuntimeDriver(FakePLC)
        self.addCleanup(driver.close)
        driver.configure(project)
        driver.poll(0)  # Fake metadata opens only; no leased tag reads.
        clients = {name: route.client for name, route in driver.connections.items()}
        return driver, clients

    def test_client_close_errors_are_logged_and_all_routes_detach(self):
        driver, clients = self.fixture()
        with patch.object(clients['plc'], 'close', side_effect=OSError('Offline first close failure')) as first, \
             patch.object(clients['last'], 'close', side_effect=OSError('Offline last close failure')) as last:
            with self.assertLogs(level='ERROR') as logs:
                driver.close()
        first.assert_called_once(); last.assert_called_once()
        self.assertTrue(clients['other'].closed)
        self.assertEqual(len(logs.output), 2)
        self.assertTrue(any('PLC client cleanup failed for route plc' in line for line in logs.output))
        self.assertTrue(any('PLC client cleanup failed for route last' in line for line in logs.output))
        for route in driver.connections.values():
            self.assertIsNone(route.client)
            self.assertFalse(route.connected)
        self.assertIsNone(driver._scan_pool)
        self.assertFalse(driver._closing)
        # Repeated shutdown does not call a detached client or emit more failures.
        with patch('openhmi.logix_transport.logging.exception') as log:
            driver.close()
        log.assert_not_called()
        self.assertTrue(all(not client.writes for client in clients.values()))

    def test_route_wrapper_errors_do_not_skip_other_routes_or_leave_scan_state(self):
        driver, clients = self.fixture()
        attempts = []
        with ExitStack() as stack:
            for name, route in driver.connections.items():
                original = route.close
                def close(name=name, original=original):
                    self.assertFalse(driver.lock._is_owned())
                    self.assertTrue(driver.io_lock._is_owned())
                    attempts.append(name)
                    original()
                    if name != 'other':
                        raise RuntimeError('Offline route wrapper failure')
                stack.enter_context(patch.object(route, 'close', side_effect=close))
            driver.samples['fixture'] = {'value': 1}
            driver.deadlines[('plc', 'fixture')] = 1
            driver._refresh_after['fixture'] = 1
            driver._bad_tag_retry_at[('plc', 'fixture')] = 10
            with self.assertLogs(level='ERROR') as logs:
                driver.close()
        self.assertEqual(attempts, ['plc', 'other', 'last'])
        self.assertEqual(len(logs.output), 2)
        self.assertTrue(any('PLC route cleanup failed for route plc' in line for line in logs.output))
        self.assertTrue(any('PLC route cleanup failed for route last' in line for line in logs.output))
        for state in (driver.samples, driver.deadlines, driver._refresh_after, driver._bad_tag_retry_at,
                      driver._scans, driver._scan_started):
            self.assertEqual(state, {})
        self.assertTrue(all(client.closed for client in clients.values()))
        self.assertTrue(all(not client.writes for client in clients.values()))

    def test_shutdown_drains_active_scan_before_closing_and_can_reopen_explicitly(self):
        driver, clients = self.fixture()
        entered, release, draining = Event(), Event(), Event()
        original_read = clients['plc'].read
        def read(*addresses):
            entered.set()
            if not release.wait(10):
                raise RuntimeError('Offline test did not release its read')
            return original_read(*addresses)
        clients['plc'].read = read
        driver.lease('viewer', ['fast'], 1)
        driver.poll(1, wait=False)
        self.assertTrue(entered.wait(5))
        pool = driver._scan_pool
        original_shutdown = pool.shutdown
        def shutdown(**kwargs):
            draining.set()
            return original_shutdown(**kwargs)
        try:
            with patch.object(pool, 'shutdown', side_effect=shutdown), ThreadPoolExecutor(max_workers=1) as closer:
                future = closer.submit(driver.close)
                try:
                    self.assertTrue(draining.wait(5))
                    self.assertFalse(future.done())
                    self.assertTrue(all(not client.closed for client in clients.values()))
                    self.assertTrue(driver._closing)
                    driver.poll(1.1, wait=False)  # No replacement scan while closing.
                finally:
                    release.set()
                future.result(timeout=5)
        finally:
            release.set()
        self.assertTrue(all(client.closed for client in clients.values()))
        self.assertTrue(all(not client.writes for client in clients.values()))
        self.assertEqual(driver._scans, {})
        self.assertEqual(driver.samples, {})  # The finishing scan cannot publish after shutdown starts.
        self.assertIsNone(driver._scan_pool)
        driver.poll(2)
        self.assertTrue(all(route.connected for route in driver.connections.values()))
        self.assertTrue(all(route.client is not clients[name] for name, route in driver.connections.items()))
