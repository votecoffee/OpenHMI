"""Offline upload admission, backpressure and dispatch revalidation contracts."""
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from httpx import ASGITransport, AsyncClient
from starlette.requests import ClientDisconnect
from openhmi.workspace import ProjectWorkspace


class ImportUploadTests(unittest.IsolatedAsyncioTestCase):
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
        backup = workspace.export()
        context = original.router.lifespan_context(original)
        await context.__aenter__()
        workspace.context = context
        self.addAsyncCleanup(workspace._shutdown)
        client = AsyncClient(transport=ASGITransport(app=workspace), base_url='http://test')
        self.addAsyncCleanup(client.aclose)
        return workspace, original, client, backup

    def upload(self, client, backup, *, headers=None):
        entered, release = asyncio.Event(), asyncio.Event()
        async def chunks():
            yield backup[:8]
            entered.set()
            await release.wait()
            yield backup[8:]
        task = asyncio.create_task(client.post('/api/workspace/import?name=Imported', content=chunks(), headers=headers))
        async def settle():
            release.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.addAsyncCleanup(settle)
        return task, entered, release

    def assert_no_import(self, workspace, invoke):
        invoke.assert_not_called()
        self.assertFalse((workspace.root / 'Imported.openhmi.sqlite3').exists())
        self.assertFalse(workspace.upload_lock.locked())
        self.assertFalse(workspace.lock.locked())

    async def test_slow_upload_allows_reads_and_rejects_switch_before_dispatch_even_without_header(self):
        for pinned in (False, True):
            with self.subTest(pinned=pinned):
                workspace, original, client, backup = await self.fixture()
                identity = original.state.project_instance
                with patch.object(workspace, 'import_backup', wraps=workspace.import_backup) as invoke:
                    task, entered, release = self.upload(client, backup, headers={'X-OpenHMI-Project': identity} if pinned else None)
                    await asyncio.wait_for(entered.wait(), 10)
                    self.assertFalse(workspace.lock.locked())
                    self.assertTrue(workspace.upload_lock.locked())
                    self.assertEqual((await asyncio.wait_for(client.get('/api/project'), 10)).status_code, 200)
                    self.assertEqual((await asyncio.wait_for(client.get('/api/workspace'), 10)).status_code, 200)
                    switched = await asyncio.wait_for(client.post('/api/workspace/open', json={'file': 'Candidate.openhmi.sqlite3'}), 10)
                    self.assertEqual(switched.status_code, 200)
                    release.set()
                    response = await asyncio.wait_for(task, 10)
                    self.assertEqual(response.status_code, 409)
                    self.assertIn('no project was imported', response.json()['detail'])
                    self.assertEqual(response.headers['x-openhmi-project'], identity)
                    self.assert_no_import(workspace, invoke)
                original.state.driver.factory.assert_not_called()

    async def test_successful_upload_rechecks_authorization_and_imports_once(self):
        workspace, original, client, backup = await self.fixture()
        with patch.object(workspace, 'require_management', wraps=workspace.require_management) as authorize, \
             patch.object(workspace, 'import_backup', wraps=workspace.import_backup) as invoke:
            task, entered, release = self.upload(client, backup)
            await asyncio.wait_for(entered.wait(), 10)
            self.assertEqual(authorize.call_count, 1)
            release.set()
            response = await asyncio.wait_for(task, 10)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(authorize.call_count, 2)
            invoke.assert_called_once_with('Imported', backup)
        self.assertEqual(response.json(), {'file': 'Imported.openhmi.sqlite3', 'handlers_saved_for_review': False, 'plc_hold': True})
        self.assertTrue((workspace.root / 'Imported.openhmi.hold').exists())
        self.assertEqual(response.headers['x-openhmi-project'], original.state.project_instance)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertFalse(workspace.upload_lock.locked())

    async def test_expired_session_during_upload_is_rejected_before_import(self):
        from tests.test_security import bootstrap, PASSWORD
        workspace, original, client, backup = await self.fixture()
        bootstrap(original)
        signed_in = await client.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD})
        self.assertEqual(signed_in.status_code, 200)
        with patch.object(workspace, 'import_backup') as invoke:
            task, entered, release = self.upload(client, backup)
            await asyncio.wait_for(entered.wait(), 10)
            signed_out = await asyncio.wait_for(client.post('/api/security/logout'), 10)
            self.assertEqual(signed_out.status_code, 200)
            release.set()
            response = await asyncio.wait_for(task, 10)
            self.assertEqual(response.status_code, 401)
            self.assert_no_import(workspace, invoke)

    async def test_admission_denial_stale_identity_and_busy_slot_do_not_consume_body(self):
        workspace, original, client, backup = await self.fixture()
        reads = []
        async def body():
            reads.append(True)
            yield backup
        with patch.object(workspace, 'import_backup') as invoke:
            stale = await client.post('/api/workspace/import?name=Imported', content=body(), headers={'X-OpenHMI-Project': 'f' * 32})
            self.assertEqual(stale.status_code, 409)
            self.assertEqual(reads, [])
            task, entered, release = self.upload(client, backup)
            await asyncio.wait_for(entered.wait(), 10)
            busy = await client.post('/api/workspace/import?name=Imported', content=body())
            self.assertEqual(busy.status_code, 429)
            self.assertEqual(reads, [])
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task
            self.assert_no_import(workspace, invoke)
            from tests.test_security import bootstrap
            bootstrap(original)
            denied = await client.post('/api/workspace/import?name=Imported', content=body())
            self.assertEqual(denied.status_code, 401)
            self.assertEqual(reads, [])
            self.assert_no_import(workspace, invoke)

    async def test_deadline_disconnect_and_overflow_release_slot_without_dispatch_or_extra_reads(self):
        workspace, _, client, backup = await self.fixture()
        replies = []
        with patch.object(workspace, 'import_backup') as invoke:
            with patch('openhmi.workspace_import.UPLOAD_SECONDS', 0.05):
                task, _, _ = self.upload(client, backup)
                response = await asyncio.wait_for(task, 10)
            self.assertEqual(response.status_code, 408)
            replies.append(response)
            self.assert_no_import(workspace, invoke)
            async def disconnected():
                yield b'partial'
                raise ClientDisconnect()
            response = await client.post('/api/workspace/import?name=Imported', content=disconnected())
            self.assertEqual(response.status_code, 400)
            replies.append(response)
            self.assert_no_import(workspace, invoke)
            reads = []
            async def overflow():
                for chunk in (b'a' * 8, b'b' * 9, b'never consumed'):
                    reads.append(chunk)
                    yield chunk
            with patch('openhmi.workspace.MAX_BACKUP', 16):
                response = await client.post('/api/workspace/import?name=Imported', content=overflow())
            self.assertEqual(response.status_code, 413)
            replies.append(response)
            self.assertEqual(len(reads), 2)
            self.assert_no_import(workspace, invoke)
        from tests.test_frontend_contract import frontend
        result = frontend('workspace_operations',
                          requests=[dict(kind='import', name='Imported', bytes=list(backup)) for _ in replies],
                          replies=[dict(status=response.status_code, data=response.json()) for response in replies])
        self.assertEqual([item['status'] for item in result['results']], [408, 400, 413])
        self.assertTrue(all(not item['requiresReview'] for item in result['results']))
        self.assertEqual(len(result['calls']), len(replies))
        self.assertTrue(all(bytes(call['bytes']) == backup for call in result['calls']))
        # A later explicit request can use the released slot.
        response = await client.post('/api/workspace/import?name=Recovered', content=backup)
        self.assertEqual(response.status_code, 200, response.text)

    async def test_shutdown_does_not_wait_for_upload_and_prevents_dispatch_on_closed_runtime(self):
        workspace, original, client, backup = await self.fixture()
        with patch.object(workspace, 'import_backup') as invoke:
            task, entered, release = self.upload(client, backup)
            await asyncio.wait_for(entered.wait(), 10)
            await asyncio.wait_for(workspace._shutdown(), 10)
            self.assertFalse(task.done())
            self.assertIsNone(workspace.context)
            release.set()
            response = await asyncio.wait_for(task, 10)
            self.assertEqual(response.status_code, 503)
            self.assert_no_import(workspace, invoke)
            response = await client.post('/api/workspace/import?name=Imported', content=backup)
            self.assertEqual(response.status_code, 503)
            self.assert_no_import(workspace, invoke)
        original.state.driver.factory.assert_not_called()
