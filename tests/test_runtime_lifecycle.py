"""Offline resource ownership across partial assembly and lifespan failures."""
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from openhmi import server
from openhmi.identity_publish import IdentityPublisher
from openhmi.logix import RuntimeDriver
from openhmi.projects import ProjectStore
from openhmi.trend_recording import TrendRecorder


class RuntimeLifecycleTests(unittest.TestCase):
    def track(self, resource, method, name, events):
        original = getattr(resource, method)
        def cleanup():
            events.append(name)
            return original()
        setattr(resource, method, Mock(side_effect=cleanup))
        return resource

    def assembly_spies(self, stack, events):
        resources = {}
        def factory(kind, name, method):
            def construct(*args, **kwargs):
                resource = self.track(kind(*args, **kwargs), method, name, events)
                resources[name] = resource
                if name == 'acquisition':
                    resource.factory = Mock(side_effect=AssertionError('Offline test cannot open a PLC connection'))
                return resource
            return construct
        for symbol, kind, name, method in [('ProjectStore', ProjectStore, 'project store', 'close'),
            ('RuntimeDriver', RuntimeDriver, 'acquisition', 'close'),
            ('TrendRecorder', TrendRecorder, 'trends', 'shutdown'),
            ('IdentityPublisher', IdentityPublisher, 'identity', 'shutdown')]:
            stack.enter_context(patch.object(server, symbol, side_effect=factory(kind, name, method)))
        return resources

    def assert_closed(self, resources):
        store = resources['project store']
        store.close.assert_called_once()
        with self.assertRaises(sqlite3.ProgrammingError):
            store._db.execute('SELECT 1')
        if 'acquisition' in resources:
            resources['acquisition'].close.assert_called_once()
            resources['acquisition'].factory.assert_not_called()

    def test_partial_construction_closes_owned_resources_without_identity_publication(self):
        cases = [('driver', 'RuntimeDriver', None), ('application', 'Application', None),
                 ('configure', None, RuntimeDriver), ('history', 'Historian', None),
                 ('trends', None, TrendRecorder), ('security', 'Security', None),
                 ('routes', 'add_recipe_routes', None), ('assets', 'StaticFiles', None)]
        for label, symbol, kind in cases:
            with self.subTest(stage=label), ExitStack() as stack:
                events = []
                resources = self.assembly_spies(stack, events)
                failure = RuntimeError('Offline ' + label + ' assembly failure')
                stack.enter_context(patch.object(server, symbol, side_effect=failure) if symbol
                                    else patch.object(kind, 'configure', side_effect=failure))
                with self.assertRaises(RuntimeError) as raised:
                    server.create_app()
                self.assertIs(raised.exception, failure)
                expected = (['trends'] if 'trends' in resources else [])
                expected += (['acquisition'] if 'acquisition' in resources else []) + ['project store']
                self.assertEqual(events, expected)
                self.assert_closed(resources)
                if 'identity' in resources:
                    resources['identity'].shutdown.assert_not_called()

    def test_real_handler_failure_and_cleanup_error_keep_original_failure(self):
        with TemporaryDirectory() as directory, ExitStack() as stack:
            handler = Path(directory) / 'fixture.py'
            handler.write_text('def register(app):\n    raise ValueError("Offline handler failed")\n', encoding='utf-8')
            events = []
            resources = self.assembly_spies(stack, events)
            def fail_cleanup(self):
                raise RuntimeError('Offline trends cleanup failure')
            stack.enter_context(patch.object(TrendRecorder, 'shutdown', fail_cleanup))
            with self.assertLogs(level='ERROR') as logs, self.assertRaisesRegex(ValueError, 'Offline handler failed'):
                server.create_app(handlers=handler)
            self.assertEqual(events, ['trends', 'acquisition', 'project store'])
            self.assert_closed(resources)
            self.assertTrue(any('Runtime cleanup failed for trends' in line for line in logs.output))

    def fixture(self):
        app = server.create_app()
        events = []
        for resource, method, name in [(app.state.trends, 'shutdown', 'trends'),
            (app.state.identity_publisher, 'shutdown', 'identity'),
            (app.state.driver, 'close', 'acquisition'), (app.state.store, 'close', 'project store')]:
            self.track(resource, method, name, events)
        app.state.driver.factory = Mock(side_effect=AssertionError('Offline test cannot open a PLC connection'))
        return app, events

    def test_initial_sample_failure_closes_resources_before_workers_start(self):
        app, events = self.fixture()
        failure = RuntimeError('Offline initial sampling failure')
        app.state.alarms.lock = Mock()
        app.state.alarms.lock.__enter__ = Mock(side_effect=failure)
        app.state.alarms.lock.__exit__ = Mock(return_value=False)
        app.state.runtime_workers.running = Mock()
        with self.assertRaises(RuntimeError) as raised, TestClient(app):
            self.fail('Startup failure cannot serve requests')
        self.assertIs(raised.exception, failure)
        app.state.runtime_workers.running.assert_not_called()
        app.state.identity_publisher.shutdown.assert_not_called()
        self.assertEqual(events, ['trends', 'acquisition', 'project store'])
        app.state.driver.factory.assert_not_called()

    def test_worker_start_failure_still_cleans_up_and_preserves_failure(self):
        app, events = self.fixture()
        failure = RuntimeError('Offline worker start failure')
        @asynccontextmanager
        async def running():
            raise failure
            yield
        app.state.runtime_workers.running = running
        with self.assertRaises(RuntimeError) as raised, TestClient(app):
            self.fail('Startup failure cannot serve requests')
        self.assertIs(raised.exception, failure)
        self.assertEqual(events, ['trends', 'identity', 'acquisition', 'project store'])
        app.state.driver.factory.assert_not_called()

    def test_workers_exit_before_independent_cleanup_and_body_failure_survives(self):
        app, events = self.fixture()
        failure = ValueError('Offline context body failure')
        @asynccontextmanager
        async def running():
            try:
                yield
            finally:
                events.append('workers stopped')
        app.state.runtime_workers.running = running
        for resource in (app.state.trends, app.state.identity_publisher):
            original = resource.shutdown.side_effect
            def fail_cleanup(original=original):
                original()
                raise RuntimeError('Offline cleanup failure')
            resource.shutdown.side_effect = fail_cleanup
        with self.assertLogs(level='ERROR') as logs, self.assertRaises(ValueError) as raised:
            with TestClient(app) as client:
                self.assertEqual(client.get('/api/project').status_code, 200)
                raise failure
        self.assertIs(raised.exception, failure)
        self.assertEqual(events, ['workers stopped', 'trends', 'identity', 'acquisition', 'project store'])
        self.assertEqual(len(logs.output), 2)
        app.state.driver.factory.assert_not_called()

    def test_worker_exit_failure_does_not_skip_resource_cleanup(self):
        app, events = self.fixture()
        failure = RuntimeError('Offline worker exit failure')
        @asynccontextmanager
        async def running():
            yield
            events.append('workers exited')
            raise failure
        app.state.runtime_workers.running = running
        with self.assertRaises(RuntimeError) as raised:
            with TestClient(app) as client:
                self.assertEqual(client.get('/api/project').status_code, 200)
        self.assertIs(raised.exception, failure)
        self.assertEqual(events, ['workers exited', 'trends', 'identity', 'acquisition', 'project store'])
        app.state.driver.factory.assert_not_called()
