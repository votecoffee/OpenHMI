"""Offline ASGI backpressure and disconnect checks with real SQL/ZIP archives."""
import asyncio
from contextlib import closing
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import Mock, patch
import zipfile

from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from openhmi.workspace import ProjectWorkspace


class BackupTransferTests(unittest.IsolatedAsyncioTestCase):
    async def fixture(self):
        directory = self.enterContext(TemporaryDirectory())
        workspace = ProjectWorkspace(Path(directory) / 'Original.openhmi.sqlite3', hold_connections=True)
        workspace.create('Candidate', 'Candidate machine')
        original = workspace.current
        factory = workspace._app
        def offline_app(*args, **kwargs):
            app = factory(*args, **kwargs)
            app.state.driver.factory = Mock(side_effect=AssertionError('Offline test cannot contact a PLC'))
            return app
        self.enterContext(patch.object(workspace, '_app', side_effect=offline_app))
        original.state.driver.factory = Mock(side_effect=AssertionError('Offline test cannot contact a PLC'))
        context = original.router.lifespan_context(original)
        await context.__aenter__()
        workspace.context = context
        self.addAsyncCleanup(workspace._shutdown)
        client = self.client(workspace)
        return workspace, original, client

    def client(self, app):
        client = AsyncClient(transport=ASGITransport(app=app), base_url='http://test')
        self.addAsyncCleanup(client.aclose)
        return client

    def paused_download(self, workspace, phase, *, headers=None, fail=False):
        entered, release = asyncio.Event(), asyncio.Event()
        messages = []
        async def app(scope, receive, send):
            async def paused_send(message):
                messages.append(message)
                if message['type'] == phase:
                    entered.set()
                    await release.wait()
                    if fail:
                        raise OSError('Synthetic disconnected backup client')
                await send(message)
            await workspace(scope, receive, paused_send)
        task = asyncio.create_task(self.client(app).get('/api/workspace/backup', headers=headers))
        async def settle():
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.addAsyncCleanup(settle)
        return task, entered, release, messages

    def assert_closed(self, app):
        with self.assertRaises(sqlite3.ProgrammingError):
            app.state.store._db.execute('SELECT 1')
        app.state.driver.factory.assert_not_called()

    def archive_title(self, workspace, data):
        with zipfile.ZipFile(BytesIO(data)) as archive:
            self.assertIsNone(archive.testzip())
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['format'], 'OpenHMI-backup')
            database = workspace.root / 'downloaded-fixture.sqlite3'
            database.write_bytes(archive.read('project.sqlite3'))
        with closing(sqlite3.connect(database)) as db:
            return json.loads(db.execute('SELECT state FROM project WHERE id=1').fetchone()[0])['active']['title']

    async def test_slow_headers_or_body_allow_reads_switch_and_shutdown_without_rebinding(self):
        for phase in ('http.response.start', 'http.response.body'):
            with self.subTest(phase=phase):
                workspace, original, client = await self.fixture()
                identity = original.state.project_instance
                title = original.state.store.snapshot()['active']['title']
                prepared = []
                export = workspace.export
                def capture():
                    data = export(); prepared.append(data); return data
                with patch.object(workspace, 'export', side_effect=capture) as invoke:
                    task, entered, release, messages = self.paused_download(workspace, phase, headers={'X-OpenHMI-Project': identity})
                    await asyncio.wait_for(entered.wait(), 10)
                    self.assertFalse(task.done())
                    self.assertFalse(workspace.lock.locked())
                    self.assertEqual((await asyncio.wait_for(client.get('/api/project'), 10)).status_code, 200)
                    self.assertEqual((await asyncio.wait_for(client.get('/api/workspace'), 10)).json()['current'], 'Original.openhmi.sqlite3')
                    opened = await asyncio.wait_for(client.post('/api/workspace/open', json={'file': 'Candidate.openhmi.sqlite3'}), 10)
                    self.assertEqual(opened.status_code, 200, opened.text)
                    candidate = workspace.current
                    self.assertNotEqual(candidate.state.project_instance, identity)
                    self.assert_closed(original)
                    self.assertFalse(task.done())
                    await asyncio.wait_for(workspace._shutdown(), 10)
                    self.assert_closed(candidate)
                    self.assertFalse(task.done())
                    release.set()
                    response = await asyncio.wait_for(task, 10)
                    invoke.assert_called_once()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers['x-openhmi-project'], identity)
                self.assertEqual(response.headers['cache-control'], 'no-store')
                self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
                self.assertEqual(response.content, prepared[0])
                self.assertEqual(self.archive_title(workspace, response.content), title)
                self.assertEqual([message['type'] for message in messages], ['http.response.start', 'http.response.body'])

    async def test_preparation_keeps_source_open_and_queued_requests_wait_until_zip_is_ready(self):
        workspace, original, client = await self.fixture()
        entered, release = asyncio.Event(), Event()
        loop = asyncio.get_running_loop()
        export = workspace.export
        def prepare():
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(20):
                raise RuntimeError('Offline test did not release backup preparation')
            return export()
        with patch.object(workspace, 'export', side_effect=prepare) as invoke:
            task = asyncio.create_task(client.get('/api/workspace/backup'))
            followers = []
            try:
                await asyncio.wait_for(entered.wait(), 10)
                followers = [asyncio.create_task(client.get('/api/workspace')),
                             asyncio.create_task(client.post('/api/workspace/open', json={'file': 'Candidate.openhmi.sqlite3'}))]
                await asyncio.sleep(0)
                self.assertTrue(workspace.lock.locked())
                self.assertTrue(all(not follower.done() for follower in followers))
                self.assertIs(workspace.current, original)
                self.assertEqual(original.state.store._db.execute('SELECT 1').fetchone(), (1,))
            finally:
                release.set()
                results = await asyncio.wait_for(asyncio.gather(task, *followers), 10)
            invoke.assert_called_once()
        self.assertTrue(all(response.status_code == 200 for response in results))
        self.assertEqual(results[0].headers['x-openhmi-project'], original.state.project_instance)
        self.assertEqual(results[1].json()['current'], 'Original.openhmi.sqlite3')
        self.assertEqual(workspace.path.name, 'Candidate.openhmi.sqlite3')
        self.assert_closed(original)

    async def test_cancelled_or_disconnected_send_releases_no_runtime_work_and_never_replays(self):
        for fail in (False, True):
            for phase in ('http.response.start', 'http.response.body'):
                with self.subTest(fail=fail, phase=phase):
                    workspace, original, client = await self.fixture()
                    with patch.object(workspace, 'export', wraps=workspace.export) as invoke:
                        task, entered, release, _ = self.paused_download(workspace, phase, fail=fail)
                        await asyncio.wait_for(entered.wait(), 10)
                        if fail:
                            release.set()
                            with self.assertRaisesRegex(OSError, 'Synthetic disconnected'):
                                await asyncio.wait_for(task, 10)
                        else:
                            task.cancel()
                            with self.assertRaises(asyncio.CancelledError):
                                await asyncio.wait_for(task, 10)
                        invoke.assert_called_once()
                    self.assertFalse(workspace.lock.locked())
                    self.assertIs(workspace.current, original)
                    self.assertEqual((await asyncio.wait_for(client.get('/api/project'), 10)).status_code, 200)
                    self.assertEqual(original.state.store._db.execute('SELECT 1').fetchone(), (1,))
                    original.state.driver.factory.assert_not_called()
                    await workspace._shutdown()

    async def test_failed_backup_send_is_detached_and_preserves_source_error_context(self):
        workspace, original, client = await self.fixture()
        with patch.object(workspace, 'export', side_effect=HTTPException(413, 'Synthetic backup limit')) as invoke:
            task, entered, release, _ = self.paused_download(workspace, 'http.response.body')
            await asyncio.wait_for(entered.wait(), 10)
            self.assertFalse(workspace.lock.locked())
            opened = await asyncio.wait_for(client.post('/api/workspace/open', json={'file': 'Candidate.openhmi.sqlite3'}), 10)
            self.assertEqual(opened.status_code, 200)
            self.assert_closed(original)
            release.set()
            response = await asyncio.wait_for(task, 10)
            invoke.assert_called_once()
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.json(), {'detail': 'Synthetic backup limit'})
        self.assertEqual(response.headers['x-openhmi-project'], original.state.project_instance)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn('content-disposition', response.headers)
