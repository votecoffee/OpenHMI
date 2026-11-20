"""Bounded workspace thread cancellation tests with synthetic SQL/backups."""
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


class WorkspaceJobTests(unittest.IsolatedAsyncioTestCase):
    async def fixture(self):
        directory = self.enterContext(TemporaryDirectory())
        workspace = ProjectWorkspace(Path(directory) / 'Original.openhmi.sqlite3', hold_connections=True)
        workspace.create('Candidate', 'Candidate machine')
        original = workspace.current
        original.state.driver.factory = Mock(side_effect=AssertionError('Offline test cannot connect to a PLC'))
        backup = workspace.export()
        context = original.router.lifespan_context(original)
        await context.__aenter__()
        workspace.context = context
        self.addAsyncCleanup(workspace._shutdown)
        client = AsyncClient(transport=ASGITransport(app=workspace), base_url='http://test')
        self.addAsyncCleanup(client.aclose)
        return workspace, original, client, backup

    def request(self, client, operation, backup):
        if operation == 'export':
            return client.get('/api/workspace/backup')
        if operation == 'create':
            return client.post('/api/workspace/create', json={'name': 'Created', 'title': 'Created machine'})
        return client.post('/api/workspace/import?name=Imported', content=backup)

    def title(self, path):
        with closing(sqlite3.connect(path)) as db:
            return json.loads(db.execute('SELECT state FROM project WHERE id=1').fetchone()[0])['active']['title']

    async def test_cancelled_jobs_finish_before_queued_switch_and_are_not_replayed(self):
        for operation, method in [('export', 'export'), ('create', 'create'), ('import', 'import_backup')]:
            with self.subTest(operation=operation):
                workspace, original, client, backup = await self.fixture()
                loop = asyncio.get_running_loop()
                entered, release = asyncio.Event(), Event()
                order, results = [], []
                original_job = getattr(workspace, method)
                original_close = original.state.store.close
                original_title = original.state.store.snapshot()['active']['title']
                def close():
                    self.assertEqual(order, ['job finished'])
                    original_close()
                    order.append('store closed')
                original.state.store.close = close
                def job(*args):
                    loop.call_soon_threadsafe(entered.set)
                    if not release.wait(10):
                        raise RuntimeError('Offline test did not release job')
                    result = original_job(*args)
                    results.append(result)
                    order.append('job finished')
                    return result
                follower = None
                with patch.object(workspace, method, side_effect=job) as invoke:
                    task = asyncio.create_task(self.request(client, operation, backup))
                    try:
                        await asyncio.wait_for(entered.wait(), 5)
                        task.cancel()
                        await asyncio.sleep(0)
                        task.cancel()
                        follower = asyncio.create_task(client.post('/api/workspace/open', json={'file': 'Candidate.openhmi.sqlite3'}))
                        await asyncio.sleep(0)
                        self.assertFalse(task.done())
                        self.assertFalse(follower.done())
                        self.assertTrue(workspace.lock.locked())
                        self.assertIs(workspace.current, original)
                        self.assertEqual(original.state.store._db.execute('SELECT 1').fetchone(), (1,))
                    finally:
                        release.set()
                        with self.assertRaises(asyncio.CancelledError):
                            await asyncio.wait_for(asyncio.shield(task), 5)
                        if follower:
                            response = await asyncio.wait_for(follower, 5)
                    invoke.assert_called_once()
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(order, ['job finished', 'store closed'])
                self.assertEqual(workspace.path.name, 'Candidate.openhmi.sqlite3')
                if operation == 'create':
                    self.assertEqual(self.title(workspace.root / 'Created.openhmi.sqlite3'), 'Created machine')
                elif operation == 'import':
                    self.assertEqual(self.title(workspace.root / 'Imported.openhmi.sqlite3'), original_title)
                    self.assertTrue((workspace.root / 'Imported.openhmi.hold').exists())
                else:
                    with zipfile.ZipFile(BytesIO(results[0])) as archive:
                        exported = workspace.root / 'exported-fixture.sqlite3'
                        exported.write_bytes(archive.read('project.sqlite3'))
                        self.assertIn('manifest.json', archive.namelist())
                    self.assertEqual(self.title(exported), original_title)
                original.state.driver.factory.assert_not_called()
                await workspace._shutdown()

    async def test_shutdown_waits_for_cancelled_background_job_before_closing_store(self):
        workspace, original, client, backup = await self.fixture()
        loop = asyncio.get_running_loop()
        entered, release, finished = asyncio.Event(), Event(), Event()
        create = workspace.create
        def job(*args):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(10):
                raise RuntimeError('Offline test did not release create')
            result = create(*args)
            finished.set()
            return result
        original_close = original.state.store.close
        def close():
            self.assertTrue(finished.is_set())
            original_close()
        original.state.store.close = close
        shutdown = None
        with patch.object(workspace, 'create', side_effect=job):
            task = asyncio.create_task(self.request(client, 'create', backup))
            try:
                await asyncio.wait_for(entered.wait(), 5)
                task.cancel()
                shutdown = asyncio.create_task(workspace._shutdown())
                await asyncio.sleep(0)
                self.assertFalse(shutdown.done())
                self.assertIsNotNone(workspace.context)
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(asyncio.shield(task), 5)
                if shutdown:
                    await asyncio.wait_for(shutdown, 5)
        self.assertIsNone(workspace.context)
        self.assertEqual(self.title(workspace.root / 'Created.openhmi.sqlite3'), 'Created machine')
        original.state.driver.factory.assert_not_called()

    async def test_background_failure_after_cancellation_is_logged_without_hiding_cancellation(self):
        workspace, original, client, backup = await self.fixture()
        loop = asyncio.get_running_loop()
        entered, release = asyncio.Event(), Event()
        def job(*args):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(10):
                raise RuntimeError('Offline test did not release failing job')
            raise OSError('Private offline background failure marker')
        with patch.object(workspace, 'create', side_effect=job) as invoke, self.assertLogs(level='ERROR') as logs:
            task = asyncio.create_task(self.request(client, 'create', backup))
            try:
                await asyncio.wait_for(entered.wait(), 5)
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
            finally:
                release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(asyncio.shield(task), 5)
            invoke.assert_called_once()
        self.assertTrue(any('Owned work failed while cancellation was pending' in line for line in logs.output))
        self.assertTrue(any('Private offline background failure marker' in line for line in logs.output))
        self.assertFalse((workspace.root / 'Created.openhmi.sqlite3').exists())
        self.assertFalse(workspace.lock.locked())
        self.assertIs(workspace.current, original)
        self.assertEqual((await client.get('/api/project')).status_code, 200)
        original.state.driver.factory.assert_not_called()

    async def test_ordinary_background_http_errors_preserve_status_detail_and_identity(self):
        workspace, original, client, _ = await self.fixture()
        with patch.object(workspace, 'export', side_effect=HTTPException(413, 'Offline export limit')) as export:
            response = await client.get('/api/workspace/backup')
        export.assert_called_once()
        self.assertEqual((response.status_code, response.json()['detail']), (413, 'Offline export limit'))
        responses = [response,
            await client.post('/api/workspace/create', json={'name': 'Candidate', 'title': 'Already exists'}),
            await client.post('/api/workspace/import?name=Invalid', content=b'not a ZIP')]
        self.assertEqual([response.status_code for response in responses], [413, 409, 422])
        for response in responses:
            self.assertEqual(response.headers['X-OpenHMI-Project'], original.state.project_instance)
            self.assertNotIn('X-OpenHMI-Operation-ID', response.headers)
        self.assertIs(workspace.current, original)
        self.assertFalse(workspace.lock.locked())
        original.state.driver.factory.assert_not_called()

    async def test_cancelled_upload_before_dispatch_does_not_start_import(self):
        workspace, original, client, _ = await self.fixture()
        entered = asyncio.Event()
        async def upload():
            yield b'partial upload'
            entered.set()
            await asyncio.Event().wait()
        with patch.object(workspace, 'import_backup') as import_backup:
            task = asyncio.create_task(client.post('/api/workspace/import?name=Incomplete', content=upload()))
            try:
                await asyncio.wait_for(entered.wait(), 5)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)
            import_backup.assert_not_called()
        self.assertFalse((workspace.root / 'Incomplete.openhmi.sqlite3').exists())
        self.assertFalse(workspace.lock.locked())
        self.assertEqual((await client.get('/api/project')).status_code, 200)
        original.state.driver.factory.assert_not_called()
