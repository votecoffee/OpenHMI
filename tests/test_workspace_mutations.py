"""Bounded offline create/open ingress with real SQL and production JS guards."""
import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from httpx import ASGITransport, AsyncClient
from starlette.requests import ClientDisconnect
from openhmi.workspace import ProjectWorkspace


class WorkspaceMutationTests(unittest.IsolatedAsyncioTestCase):
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

    def pending(self, client, kind='create', *, headers=None):
        entered, release = asyncio.Event(), asyncio.Event()
        payload = json.dumps({'name': 'Created', 'title': 'Created machine'} if kind == 'create' else {'file': 'Candidate.openhmi.sqlite3'}).encode()
        async def chunks():
            yield payload[:4]
            entered.set()
            await release.wait()
            yield payload[4:]
        task = asyncio.create_task(client.post('/api/workspace/' + kind, content=chunks(), headers=headers))
        async def settle():
            release.set()
            if not task.done(): task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.addAsyncCleanup(settle)
        return task, entered, release

    async def test_exact_size_create_open_requests_preserve_payloads_and_source_context(self):
        workspace, original, client = await self.fixture()
        with patch.object(workspace, 'require_management', wraps=workspace.require_management) as authorize:
            for kind, payload in [('create', {'name': 'Created', 'title': '设备 machine'}), ('open', {'file': 'Created.openhmi.sqlite3'})]:
                raw = json.dumps(payload, ensure_ascii=False).encode()
                response = await client.post('/api/workspace/' + kind, content=raw + b' ' * (4096 - len(raw)))
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.headers['x-openhmi-project'], original.state.project_instance)
                self.assertEqual(response.headers['cache-control'], 'no-store')
                self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
                self.assertNotIn('x-openhmi-operation-id', response.headers)
            self.assertEqual(authorize.call_count, 4)
        self.assertEqual(response.json(), {'ok': True, 'current': 'Created.openhmi.sqlite3'})
        self.assertEqual(workspace.current.state.store.snapshot()['active']['title'], '设备 machine')
        original.state.driver.factory.assert_not_called()

    async def test_slow_body_does_not_block_reads_and_cannot_cross_project_switch(self):
        for kind, pinned in [('create', False), ('open', True)]:
            with self.subTest(kind=kind):
                workspace, original, client = await self.fixture()
                headers = {'X-OpenHMI-Project': original.state.project_instance} if pinned else None
                with patch.object(workspace, 'create', wraps=workspace.create) as create, patch.object(workspace, 'open', wraps=workspace.open) as open_project:
                    task, entered, release = self.pending(client, kind, headers=headers)
                    await asyncio.wait_for(entered.wait(), 10)
                    self.assertFalse(workspace.lock.locked())
                    self.assertEqual((await asyncio.wait_for(client.get('/api/project'), 10)).status_code, 200)
                    switched = await asyncio.wait_for(client.post('/api/workspace/open', json={'file': 'Candidate.openhmi.sqlite3'}), 10)
                    self.assertEqual(switched.status_code, 200, switched.text)
                    release.set()
                    response = await asyncio.wait_for(task, 10)
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(response.headers['x-openhmi-project'], original.state.project_instance)
                    create.assert_not_called()
                    open_project.assert_awaited_once()
                self.assertFalse((workspace.root / 'Created.openhmi.sqlite3').exists())

    async def test_denied_and_stale_admission_do_not_read_body_and_logout_revokes_dispatch(self):
        from tests.test_security import bootstrap, PASSWORD
        workspace, original, client = await self.fixture()
        bootstrap(original)
        reads = []
        async def body():
            reads.append(True)
            yield b'{}'
        with patch.object(workspace, 'create') as create:
            for headers, status in [({'X-OpenHMI-Project': 'old-instance'}, 409), ({}, 401)]:
                response = await client.post('/api/workspace/create', content=body(), headers=headers)
                self.assertEqual(response.status_code, status)
                self.assertEqual(reads, [])
            login = await client.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD})
            self.assertEqual(login.status_code, 200)
            task, entered, release = self.pending(client)
            await asyncio.wait_for(entered.wait(), 10)
            self.assertEqual((await client.post('/api/security/logout')).status_code, 200)
            release.set()
            response = await asyncio.wait_for(task, 10)
            self.assertEqual(response.status_code, 401)
            create.assert_not_called()

    async def test_pending_limit_rejects_unread_body_and_cancellation_returns_all_slots(self):
        workspace, _, client = await self.fixture()
        tasks = []
        with patch.object(workspace, 'create', wraps=workspace.create) as create:
            for _ in range(4):
                task, entered, _ = self.pending(client)
                tasks.append(task)
                await asyncio.wait_for(entered.wait(), 10)
            self.assertTrue(workspace.mutation_slots.locked())
            self.assertEqual((await client.get('/api/workspace')).status_code, 200)
            reads = []
            async def body():
                reads.append(True)
                yield b'{}'
            response = await client.post('/api/workspace/open', content=body())
            self.assertEqual(response.status_code, 429)
            self.assertEqual(reads, [])
            create.assert_not_called()
            for task in tasks: task.cancel()
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self.assertTrue(all(isinstance(result, asyncio.CancelledError) for result in results))
            self.assertFalse(workspace.mutation_slots.locked())
            response = await client.post('/api/workspace/create', json={'name': 'Created', 'title': 'Created machine'})
            self.assertEqual(response.status_code, 200, response.text)
            create.assert_called_once()

    async def test_stream_limits_timeout_disconnect_and_malformed_json_never_dispatch(self):
        workspace, _, client = await self.fixture()
        replies = []
        with patch.object(workspace, 'create') as create, patch.object(workspace, 'open') as open_project:
            reads = []
            async def overflow():
                for chunk in (b' ' * 4096, b'x', b'never read'):
                    reads.append(True)
                    yield chunk
            response = await client.post('/api/workspace/create', content=overflow())
            self.assertEqual(response.status_code, 413)
            self.assertEqual(len(reads), 2)
            replies.append(response)
            for payload in (b'\xff', b'[]', b'[' * 2000 + b'0' + b']' * 2000):
                response = await client.post('/api/workspace/open', content=payload)
                self.assertEqual(response.status_code, 422)
                replies.append(response)
            with patch('openhmi.workspace_mutations.RECEIVE_SECONDS', 0.05):
                task, _, _ = self.pending(client)
                response = await asyncio.wait_for(task, 10)
            self.assertEqual(response.status_code, 408)
            replies.append(response)
            async def disconnected():
                yield b'{'
                raise ClientDisconnect()
            response = await client.post('/api/workspace/open', content=disconnected())
            self.assertEqual(response.status_code, 400)
            replies.append(response)
            create.assert_not_called(); open_project.assert_not_called()
        from tests.test_frontend_contract import frontend
        result = frontend('workspace_operations', requests=[dict(kind='create', name='Created', title='Retained') for _ in replies],
                          replies=[dict(status=response.status_code, data=response.json()) for response in replies])
        self.assertEqual([row['status'] for row in result['results']], [413, 422, 422, 422, 408, 400])
        self.assertTrue(all(not row['requiresReview'] for row in result['results']))
        self.assertEqual(len(result['calls']), len(replies))
        self.assertFalse(workspace.lock.locked())

    async def test_shutdown_during_receive_rejects_dispatch_without_using_closed_store(self):
        workspace, _, client = await self.fixture()
        with patch.object(workspace, 'open') as open_project:
            task, entered, release = self.pending(client, 'open')
            await asyncio.wait_for(entered.wait(), 10)
            await asyncio.wait_for(workspace._shutdown(), 10)
            self.assertFalse(task.done())
            release.set()
            response = await asyncio.wait_for(task, 10)
            self.assertEqual(response.status_code, 503)
            response = await client.post('/api/workspace/open', json={'file': 'Candidate.openhmi.sqlite3'})
            self.assertEqual(response.status_code, 503)
            open_project.assert_not_called()

    async def test_slow_acknowledgement_does_not_hold_runtime_lock_or_replay_operation(self):
        for kind in ('create', 'open'):
            with self.subTest(kind=kind):
                workspace, original, _ = await self.fixture()
                entered, release = asyncio.Event(), asyncio.Event()
                async def app(scope, receive, send):
                    async def paused_send(message):
                        if message['type'] == 'http.response.body':
                            entered.set()
                            await release.wait()
                        await send(message)
                    await workspace(scope, receive, paused_send)
                client = self.client(app)
                payload = {'name': 'Created', 'title': 'Created machine'} if kind == 'create' else {'file': 'Candidate.openhmi.sqlite3'}
                with patch.object(workspace, kind, wraps=getattr(workspace, kind)) as invoke:
                    task = asyncio.create_task(client.post('/api/workspace/' + kind, json=payload))
                    try:
                        await asyncio.wait_for(entered.wait(), 10)
                        self.assertFalse(workspace.lock.locked())
                        await asyncio.wait_for(workspace._shutdown(), 10)
                    finally:
                        release.set()
                        response = await asyncio.wait_for(task, 10)
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.headers['x-openhmi-project'], original.state.project_instance)
                    invoke.assert_called_once()
