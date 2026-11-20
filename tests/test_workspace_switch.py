"""Offline workspace handoff faults with real SQL and bounded event gates."""
import asyncio
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from httpx import ASGITransport, AsyncClient
from openhmi.workspace import ProjectWorkspace


class WorkspaceSwitchTests(unittest.IsolatedAsyncioTestCase):
    async def fixture(self):
        directory = self.enterContext(TemporaryDirectory())
        workspace = ProjectWorkspace(Path(directory) / 'Original.openhmi.sqlite3', hold_connections=True)
        workspace.create('Candidate', 'Candidate machine')
        original = workspace.current
        original.state.driver.factory = Mock(side_effect=AssertionError('Offline test cannot connect to a PLC'))
        context = original.router.lifespan_context(original)
        await context.__aenter__()
        workspace.context = context
        workspace.handlers = Path(directory) / 'review-only.py'
        self.addAsyncCleanup(workspace._shutdown)
        client = AsyncClient(transport=ASGITransport(app=workspace), base_url='http://test')
        self.addAsyncCleanup(client.aclose)
        return workspace, original, client

    def candidate_factory(self, workspace, customize=None):
        original_factory = workspace._app
        candidates = []
        def create(*args, **kwargs):
            app = original_factory(*args, **kwargs)
            app.state.driver.factory = Mock(side_effect=AssertionError('Offline test cannot connect to a PLC'))
            candidates.append(app)
            if customize:
                customize(app)
            return app
        return create, candidates

    def assert_closed(self, app):
        with self.assertRaises(sqlite3.ProgrammingError):
            app.state.store._db.execute('SELECT 1')
        app.state.driver.factory.assert_not_called()

    async def test_failed_candidate_construction_or_startup_keeps_current_runtime(self):
        for stage in ('construction', 'startup'):
            with self.subTest(stage=stage):
                workspace, original, client = await self.fixture()
                context, path, handlers = workspace.context, workspace.path, workspace.handlers
                failure = RuntimeError('Private offline candidate failure marker')
                def fail_start(app):
                    lock = Mock()
                    lock.__enter__ = Mock(side_effect=failure)
                    lock.__exit__ = Mock(return_value=False)
                    app.state.alarms.lock = lock
                factory, candidates = self.candidate_factory(workspace, fail_start)
                with patch.object(workspace, '_app', side_effect=failure if stage == 'construction' else factory), \
                     self.assertLogs(level='ERROR'):
                    response = await client.post('/api/workspace/open', json={'file': 'Candidate.openhmi.sqlite3'})
                self.assertEqual(response.status_code, 503)
                self.assertIn('current project remains open', response.json()['detail'])
                self.assertNotIn('Private offline', response.text)
                self.assertEqual(response.headers['X-OpenHMI-Project'], original.state.project_instance)
                self.assertIs(workspace.current, original)
                self.assertIs(workspace.context, context)
                self.assertEqual((workspace.path, workspace.handlers), (path, handlers))
                self.assertEqual((await client.get('/api/project')).status_code, 200)
                self.assertEqual(original.state.store._db.execute('SELECT 1').fetchone(), (1,))
                for candidate in candidates:
                    self.assert_closed(candidate)
                original.state.driver.factory.assert_not_called()
                await workspace._shutdown()

    async def test_cancel_during_candidate_startup_releases_lock_after_candidate_cleanup(self):
        workspace, original, client = await self.fixture()
        context, path, handlers = workspace.context, workspace.path, workspace.handlers
        loop = asyncio.get_running_loop()
        entered, release = asyncio.Event(), Event()
        def customize(app):
            sample = app.state.alarms.sample
            def blocked():
                loop.call_soon_threadsafe(entered.set)
                if not release.wait(5):
                    raise RuntimeError('Offline test did not release candidate sample')
                sample()
            app.state.alarms.sample = blocked
        factory, candidates = self.candidate_factory(workspace, customize)
        follower = None
        with patch.object(workspace, '_app', side_effect=factory):
            task = asyncio.create_task(client.post('/api/workspace/open', json={'file': 'Candidate.openhmi.sqlite3'}))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                follower = asyncio.create_task(client.get('/api/project'))
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                self.assertFalse(follower.done())
                self.assertTrue(workspace.lock.locked())
                self.assertIs(workspace.current, original)
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(asyncio.shield(task), 2)
                if follower:
                    response = await asyncio.wait_for(follower, 2)
        self.assertEqual(response.json()['project_instance'], original.state.project_instance)
        self.assertIs(workspace.context, context)
        self.assertEqual((workspace.path, workspace.handlers), (path, handlers))
        self.assertFalse(workspace.lock.locked())
        self.assert_closed(candidates[0])
        original.state.driver.factory.assert_not_called()

    async def test_cancel_after_commit_finishes_old_shutdown_and_keeps_new_runtime_owned(self):
        workspace, original, client = await self.fixture()
        loop = asyncio.get_running_loop()
        retiring, release = asyncio.Event(), Event()
        shutdown = original.state.trends.shutdown
        def blocked():
            loop.call_soon_threadsafe(retiring.set)
            if not release.wait(5):
                raise RuntimeError('Offline test did not release old shutdown')
            shutdown()
        original.state.trends.shutdown = blocked
        factory, candidates = self.candidate_factory(workspace)
        follower = None
        with patch.object(workspace, '_app', side_effect=factory):
            task = asyncio.create_task(client.post('/api/workspace/open', json={'file': 'Candidate.openhmi.sqlite3'}))
            try:
                await asyncio.wait_for(retiring.wait(), 2)
                self.assertIs(workspace.current, candidates[0])
                self.assertEqual(workspace.path.name, 'Candidate.openhmi.sqlite3')
                self.assertIsNotNone(workspace.context)
                self.assertIsNone(workspace.handlers)
                task.cancel()
                await asyncio.sleep(0)
                task.cancel()
                follower = asyncio.create_task(client.get('/api/project'))
                await asyncio.sleep(0)
                self.assertFalse(task.done())
                self.assertFalse(follower.done())
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(asyncio.shield(task), 2)
                if follower:
                    response = await asyncio.wait_for(follower, 2)
        self.assertEqual(response.json()['project_instance'], candidates[0].state.project_instance)
        self.assert_closed(original)
        stale = await client.post('/api/controls/toggle/activate', json={},
                                  headers={'X-OpenHMI-Project': original.state.project_instance})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(candidates[0].state.activity.query()['items'], [])
        await workspace._shutdown()
        self.assertIsNone(workspace.context)
        self.assert_closed(candidates[0])

    async def test_post_commit_retirement_error_reports_new_runtime_without_replaying_open(self):
        workspace, original, client = await self.fixture()
        old_context = workspace.context
        async def fail_exit(*args):
            await old_context.__aexit__(*args)
            raise RuntimeError('Private offline retirement failure marker')
        workspace.context = SimpleNamespace(__aexit__=fail_exit)
        factory, candidates = self.candidate_factory(workspace)
        with patch.object(workspace, '_app', side_effect=factory) as create, self.assertLogs(level='ERROR'):
            response = await client.post('/api/workspace/open', json={'file': 'Candidate.openhmi.sqlite3'})
        self.assertEqual(response.status_code, 503)
        self.assertIn('requested project is now open', response.json()['detail'])
        self.assertNotIn('Private offline', response.text)
        self.assertEqual(response.headers['X-OpenHMI-Project'], original.state.project_instance)
        create.assert_called_once()
        self.assertIs(workspace.current, candidates[0])
        current = await client.get('/api/project')
        self.assertEqual(current.json()['project_instance'], candidates[0].state.project_instance)
        self.assert_closed(original)
        candidates[0].state.driver.factory.assert_not_called()

    async def lifespan_fixture(self):
        directory = self.enterContext(TemporaryDirectory())
        workspace = ProjectWorkspace(Path(directory) / 'Original.openhmi.sqlite3', hold_connections=True)
        workspace.current.state.driver.factory = Mock(side_effect=AssertionError('Offline test cannot connect to a PLC'))
        return workspace

    async def test_cancelled_workspace_lifespan_waits_for_cleanup_and_clears_ownership(self):
        workspace = await self.lifespan_fixture()
        app = workspace.current
        loop = asyncio.get_running_loop()
        ready, cleaning, release = asyncio.Event(), asyncio.Event(), Event()
        shutdown = app.state.trends.shutdown
        def blocked():
            loop.call_soon_threadsafe(cleaning.set)
            if not release.wait(5):
                raise RuntimeError('Offline test did not release lifespan cleanup')
            shutdown()
        app.state.trends.shutdown = blocked
        receives = 0
        async def receive():
            nonlocal receives
            receives += 1
            if receives == 1:
                return {'type': 'lifespan.startup'}
            await asyncio.Event().wait()
        async def send(message):
            if message['type'] == 'lifespan.startup.complete':
                ready.set()
        task = asyncio.create_task(workspace({'type': 'lifespan'}, receive, send))
        try:
            await asyncio.wait_for(ready.wait(), 2)
            task.cancel()
            await asyncio.wait_for(cleaning.wait(), 2)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.assertTrue(workspace.lock.locked())
        finally:
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(task), 2)
        self.assertIsNone(workspace.context)
        self.assertFalse(workspace.lock.locked())
        self.assert_closed(app)

    async def test_failed_startup_notification_still_shuts_down_started_runtime(self):
        workspace = await self.lifespan_fixture()
        failure = RuntimeError('Offline startup notification failure')
        async def receive():
            return {'type': 'lifespan.startup'}
        async def send(message):
            raise failure
        with self.assertRaises(RuntimeError) as raised:
            await workspace({'type': 'lifespan'}, receive, send)
        self.assertIs(raised.exception, failure)
        self.assertIsNone(workspace.context)
        self.assert_closed(workspace.current)
