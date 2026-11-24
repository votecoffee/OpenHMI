"""Offline project-library/inventory snapshot delivery and ownership checks."""
import asyncio
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import Mock, patch

from httpx import ASGITransport, AsyncClient
from openhmi.workspace import ProjectWorkspace
from openhmi.workspace_contracts import LibrarySnapshot
from openhmi.workspace_inventory import ArtifactPage, inventory

PATHS = ('/api/workspace', '/api/workspace/artifacts')


class WorkspaceReadTests(unittest.IsolatedAsyncioTestCase):
    async def fixture(self):
        directory = self.enterContext(TemporaryDirectory())
        workspace = ProjectWorkspace(Path(directory) / 'Original.openhmi.sqlite3', hold_connections=True)
        workspace.create('Candidate', 'Candidate machine')
        (workspace.root / 'Original.openhmi.hold').write_bytes(b'Synthetic fixture')
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

    def paused(self, workspace, path, phase='http.response.body', *, fail=False):
        entered, release = asyncio.Event(), asyncio.Event()
        async def app(scope, receive, send):
            async def paused_send(message):
                if message['type'] == phase:
                    entered.set()
                    await release.wait()
                    if fail: raise OSError('Synthetic disconnected read client')
                await send(message)
            await workspace(scope, receive, paused_send)
        task = asyncio.create_task(self.client(app).get(path))
        async def settle():
            release.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.addAsyncCleanup(settle)
        return task, entered, release

    def assert_closed(self, app):
        with self.assertRaises(sqlite3.ProgrammingError):
            app.state.store._db.execute('SELECT 1')
        app.state.driver.factory.assert_not_called()

    async def test_slow_headers_and_body_allow_reads_switch_shutdown_and_preserve_snapshot_contracts(self):
        bodies = {path: [] for path in PATHS}
        for path in PATHS:
            for phase in ('http.response.start', 'http.response.body'):
                with self.subTest(path=path, phase=phase):
                    workspace, original, client = await self.fixture()
                    prepared = []
                    handle = workspace.handle
                    async def prepare(request):
                        response = await handle(request)
                        if request.url.path == path: prepared.append(response.body)
                        return response
                    with patch.object(workspace, 'handle', side_effect=prepare):
                        task, entered, release = self.paused(workspace, path, phase)
                        await asyncio.wait_for(entered.wait(), 10)
                        self.assertFalse(workspace.lock.locked())
                        self.assertEqual((await asyncio.wait_for(client.get('/api/project'), 10)).status_code, 200)
                        switched = await asyncio.wait_for(client.post('/api/workspace/open', json={'file': 'Candidate.openhmi.sqlite3'}), 10)
                        self.assertEqual(switched.status_code, 200, switched.text)
                        candidate = workspace.current
                        self.assert_closed(original)
                        (workspace.root / 'Late.openhmi.hold').write_bytes(b'Added after snapshot')
                        await asyncio.wait_for(workspace._shutdown(), 10)
                        self.assert_closed(candidate)
                        self.assertFalse(task.done())
                        release.set()
                        response = await asyncio.wait_for(task, 10)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.content, prepared[0])
                    self.assertEqual(len(prepared), 1)
                    self.assertEqual(response.headers['x-openhmi-project'], original.state.project_instance)
                    self.assertEqual(response.headers['cache-control'], 'no-store')
                    self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
                    self.assertEqual(int(response.headers['content-length']), len(response.content))
                    self.assertNotIn('x-openhmi-operation-id', response.headers)
                    data = response.json()
                    if path == PATHS[0]:
                        LibrarySnapshot.model_validate(data)
                        self.assertEqual(data['current'], 'Original.openhmi.sqlite3')
                    else:
                        ArtifactPage.model_validate(data)
                        self.assertNotIn('Late.openhmi.hold', [row['file'] for row in data['items']])
                    bodies[path].append(data)
        from tests.test_frontend_contract import frontend
        self.assertEqual(frontend('workspace_library', libraries=bodies[PATHS[0]])['libraries'], [True, True])
        self.assertEqual(frontend('workspace_artifacts', pages=[{'data': body} for body in bodies[PATHS[1]]])['valid'], [True, True])

    async def test_cancelled_or_disconnected_send_never_repeats_preparation_or_retires_runtime(self):
        for path in PATHS:
            for fail in (False, True):
                with self.subTest(path=path, fail=fail):
                    workspace, original, client = await self.fixture()
                    with patch.object(workspace, 'handle', wraps=workspace.handle) as handle:
                        task, entered, release = self.paused(workspace, path, fail=fail)
                        await asyncio.wait_for(entered.wait(), 10)
                        if fail:
                            release.set()
                            with self.assertRaisesRegex(OSError, 'Synthetic disconnected'):
                                await asyncio.wait_for(task, 10)
                        else:
                            task.cancel()
                            with self.assertRaises(asyncio.CancelledError): await task
                        handle.assert_awaited_once()
                    self.assertFalse(workspace.lock.locked())
                    self.assertIs(workspace.current, original)
                    self.assertEqual((await client.get('/api/project')).status_code, 200)
                    self.assertEqual(original.state.store._db.execute('SELECT 1').fetchone(), (1,))
                    original.state.driver.factory.assert_not_called()

    async def test_cancelled_inventory_preparation_drains_before_queued_switch_closes_source(self):
        workspace, original, client = await self.fixture()
        loop = asyncio.get_running_loop()
        entered, release = asyncio.Event(), Event()
        order = []
        def scan(*args):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(20): raise RuntimeError('Offline test did not release inventory')
            result = inventory(*args)
            order.append('scan finished')
            return result
        close = original.state.store.close
        def close_source():
            self.assertEqual(order, ['scan finished'])
            close()
            order.append('source closed')
        original.state.store.close = close_source
        follower = None
        with patch('openhmi.workspace.inventory', side_effect=scan) as invoke:
            task = asyncio.create_task(client.get(PATHS[1]))
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
        self.assertEqual(order, ['scan finished', 'source closed'])
        self.assert_closed(original)

    async def test_denied_and_failed_read_replies_send_without_lock_and_keep_private_source_context(self):
        from tests.test_security import bootstrap
        for path, denied in [(PATHS[0], True), (PATHS[1], True), (PATHS[1], False)]:
            with self.subTest(path=path, denied=denied):
                workspace, original, _ = await self.fixture()
                if denied: bootstrap(original)
                with patch('openhmi.workspace_inventory.os.scandir', side_effect=PermissionError('Private failure marker')), \
                     patch('openhmi.workspace.inventory', wraps=inventory) as scan:
                    task, entered, release = self.paused(workspace, path)
                    if not denied:
                        with self.assertLogs(level='ERROR'):
                            await asyncio.wait_for(entered.wait(), 10)
                    else:
                        await asyncio.wait_for(entered.wait(), 10)
                    self.assertFalse(workspace.lock.locked())
                    await asyncio.wait_for(workspace._shutdown(), 10)
                    release.set()
                    response = await asyncio.wait_for(task, 10)
                    if denied: scan.assert_not_called()
                    else: scan.assert_called_once()
                self.assertEqual(response.status_code, 401 if denied else 503)
                self.assertNotIn('Private failure marker', response.text)
                self.assertEqual(response.headers['x-openhmi-project'], original.state.project_instance)
                self.assertEqual(response.headers['cache-control'], 'no-store')
                self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
                self.assert_closed(original)
