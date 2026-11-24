"""Offline applied-screen response ownership across apply/switch/shutdown."""
import asyncio
from copy import deepcopy
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import Mock, patch

from httpx import ASGITransport, AsyncClient
from openhmi.http_snapshot import prepare_snapshot
from openhmi.project_models import Project
from openhmi.workspace import ProjectWorkspace

PATH = '/api/project/active'


class AppliedDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def fixture(self):
        directory = self.enterContext(TemporaryDirectory())
        workspace = ProjectWorkspace(Path(directory) / 'Original.openhmi.sqlite3', hold_connections=True)
        workspace.create('Candidate', 'Candidate machine')
        original = workspace.current
        original.state.driver.factory = Mock(side_effect=AssertionError('Offline test cannot contact a PLC'))
        factory = workspace._app
        def offline_app(*args, **kwargs):
            app = factory(*args, **kwargs)
            app.state.driver.factory = Mock(side_effect=AssertionError('Offline test cannot contact a PLC'))
            return app
        self.enterContext(patch.object(workspace, '_app', side_effect=offline_app))
        context = original.router.lifespan_context(original)
        await context.__aenter__()
        workspace.context = context
        self.addAsyncCleanup(workspace._shutdown)
        return workspace, original, self.client(workspace)

    def client(self, app):
        client = AsyncClient(transport=ASGITransport(app=app), base_url='http://test')
        self.addAsyncCleanup(client.aclose)
        return client

    def paused(self, workspace, phase, *, fail=False):
        entered, release = asyncio.Event(), asyncio.Event()
        async def app(scope, receive, send):
            async def paused_send(message):
                if message['type'] == phase:
                    entered.set()
                    await release.wait()
                    if fail: raise OSError('Synthetic disconnected layout viewer')
                await send(message)
            await workspace(scope, receive, paused_send)
        task = asyncio.create_task(self.client(app).get(PATH))
        async def settle():
            release.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.addAsyncCleanup(settle)
        return task, entered, release

    def assert_closed(self, app):
        with self.assertRaises(sqlite3.ProgrammingError): app.state.store._db.execute('SELECT 1')
        app.state.driver.factory.assert_not_called()

    async def test_slow_headers_and_body_keep_revision_layout_identity_paired_through_apply_and_switch(self):
        frames = []
        for phase in ('http.response.start', 'http.response.body'):
            with self.subTest(phase=phase):
                workspace, original, client = await self.fixture()
                expected = (await client.get(PATH)).json()
                prepared = []
                async def capture(*args):
                    response = await prepare_snapshot(*args)
                    if args[1]['path'] == PATH: prepared.append(response.body)
                    return response
                with patch('openhmi.workspace.prepare_snapshot', side_effect=capture):
                    task, entered, release = self.paused(workspace, phase)
                    await asyncio.wait_for(entered.wait(), 10)
                    self.assertFalse(workspace.lock.locked())
                    self.assertEqual((await client.get('/api/tags')).status_code, 200)
                    state = (await client.get('/api/project')).json()
                    draft = deepcopy(state['draft'])
                    self.assertEqual(draft['connections'], [])  # Apply is local/synthetic only.
                    draft.update(title='New applied screen 设备', update_ms=1000)
                    saved = await asyncio.wait_for(client.put('/api/project/draft', json={'expected_revision': state['draft_revision'], 'project': draft}), 10)
                    self.assertEqual(saved.status_code, 200, saved.text)
                    self.assertEqual((await client.get(PATH)).json(), expected)
                    applied = await asyncio.wait_for(client.post('/api/project/apply', json={'expected_revision': saved.json()['draft_revision'], 'reason': 'Synthetic local-only apply'}), 10)
                    self.assertEqual(applied.status_code, 200, applied.text)
                    newer = (await client.get(PATH)).json()
                    self.assertEqual(newer['revision'], saved.json()['draft_revision'])
                    self.assertNotEqual(newer['revision'], expected['revision'])
                    self.assertEqual(newer['project']['title'], draft['title'])
                    self.assertEqual(newer['project_instance'], expected['project_instance'])
                    with patch.object(original.state.application, 'invoke', side_effect=AssertionError('Stale revision cannot dispatch')) as action:
                        stale_revision = await client.post('/api/controls/toggle/activate', json={'expected_revision': expected['revision']})
                        self.assertEqual(stale_revision.status_code, 409)
                        action.assert_not_called()
                    switched = await asyncio.wait_for(client.post('/api/workspace/open', json={'file': 'Candidate.openhmi.sqlite3'}), 10)
                    self.assertEqual(switched.status_code, 200, switched.text)
                    candidate = workspace.current
                    self.assertNotEqual(candidate.state.project_instance, expected['project_instance'])
                    self.assert_closed(original)
                    with patch.object(candidate.state.store, 'apply', side_effect=AssertionError('Stale source cannot dispatch')) as apply:
                        stale = await client.post('/api/project/apply', json={'expected_revision': 1}, headers={'X-OpenHMI-Project': expected['project_instance']})
                        self.assertEqual(stale.status_code, 409)
                        apply.assert_not_called()
                    await asyncio.wait_for(workspace._shutdown(), 10)
                    self.assert_closed(candidate)
                    self.assertFalse(task.done())
                    release.set()
                    response = await asyncio.wait_for(task, 10)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, prepared[0])
                self.assertEqual(response.json(), expected)
                self.assertEqual(response.headers['x-openhmi-project'], expected['project_instance'])
                self.assertEqual(response.headers['cache-control'], 'no-store')
                self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
                self.assertEqual(int(response.headers['content-length']), len(response.content))
                Project.model_validate(response.json()['project'])
                frames += [response.json(), newer]
        from tests.test_frontend_contract import frontend
        self.assertEqual(frontend('applied_projects', snapshots=frames)['valid'], [True] * len(frames))

    async def test_cancelled_store_projection_drains_before_queued_switch_closes_source(self):
        workspace, original, client = await self.fixture()
        snapshot = original.state.store.snapshot
        loop = asyncio.get_running_loop()
        entered, release = asyncio.Event(), Event()
        order = []
        def blocked():
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(20): raise RuntimeError('Offline test did not release store snapshot')
            result = snapshot()
            order.append('snapshot finished')
            return result
        close = original.state.store.close
        def close_source():
            self.assertEqual(order, ['snapshot finished'])
            close(); order.append('source closed')
        original.state.store.close = close_source
        follower = None
        with patch.object(original.state.store, 'snapshot', side_effect=blocked) as invoke:
            task = asyncio.create_task(client.get(PATH))
            try:
                await asyncio.wait_for(entered.wait(), 10)
                task.cancel(); await asyncio.sleep(0); task.cancel()
                follower = asyncio.create_task(client.post('/api/workspace/open', json={'file': 'Candidate.openhmi.sqlite3'}))
                await asyncio.sleep(0)
                self.assertTrue(workspace.lock.locked())
                self.assertFalse(task.done()); self.assertFalse(follower.done())
                self.assertEqual(original.state.store._db.execute('SELECT 1').fetchone(), (1,))
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError): await asyncio.wait_for(task, 10)
                if follower: response = await asyncio.wait_for(follower, 10)
            invoke.assert_called_once()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(order, ['snapshot finished', 'source closed'])
        self.assert_closed(original)

    async def test_send_cancellation_disconnect_do_not_repeat_preparation_or_retire_runtime(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                workspace, original, client = await self.fixture()
                with patch('openhmi.workspace.prepare_snapshot', wraps=prepare_snapshot) as prepare:
                    task, entered, release = self.paused(workspace, 'http.response.body', fail=fail)
                    await asyncio.wait_for(entered.wait(), 10)
                    if fail:
                        release.set()
                        with self.assertRaisesRegex(OSError, 'Synthetic disconnected'):
                            await asyncio.wait_for(task, 10)
                    else:
                        task.cancel()
                        with self.assertRaises(asyncio.CancelledError): await task
                    prepare.assert_awaited_once()
                self.assertFalse(workspace.lock.locked())
                self.assertIs(workspace.current, original)
                self.assertEqual((await client.get(PATH)).status_code, 200)
                original.state.driver.factory.assert_not_called()

    async def test_store_failure_is_private_sanitized_recoverable_and_shutdown_rejects_projection(self):
        workspace, original, client = await self.fixture()
        with patch.object(original.state.store, 'snapshot', side_effect=RuntimeError('Private SQL snapshot marker')), self.assertLogs(level='ERROR'):
            response = await client.get(PATH)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('Private SQL snapshot marker', response.text)
        self.assertEqual(response.headers['x-openhmi-project'], original.state.project_instance)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual((await client.get(PATH)).status_code, 200)
        await workspace._shutdown()
        with patch.object(original.state.store, 'snapshot') as snapshot:
            response = await client.get(PATH)
            self.assertEqual(response.status_code, 503)
            snapshot.assert_not_called()
