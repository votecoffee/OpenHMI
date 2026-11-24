"""Offline cached tag response staging through the real FastAPI middleware."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import Mock, patch

from httpx import ASGITransport, AsyncClient
from openhmi.http_snapshot import prepare_snapshot
from openhmi.workspace import ProjectWorkspace


class TagDeliveryTests(unittest.IsolatedAsyncioTestCase):
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

    def paused(self, workspace, path, phase, *, fail=False):
        entered, release = asyncio.Event(), asyncio.Event()
        async def app(scope, receive, send):
            async def paused_send(message):
                if message['type'] == phase:
                    entered.set()
                    await release.wait()
                    if fail: raise OSError('Synthetic disconnected tag viewer')
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
        with self.assertRaises(sqlite3.ProgrammingError): app.state.store._db.execute('SELECT 1')
        app.state.driver.factory.assert_not_called()

    async def test_full_and_status_only_slow_sends_preserve_quality_bytes_identity_and_subscriptions(self):
        frames = []
        for status_only in (False, True):
            for phase in ('http.response.start', 'http.response.body'):
                with self.subTest(status_only=status_only, phase=phase):
                    workspace, original, client = await self.fixture()
                    samples = {'Zero': {'value': 0, 'quality': 'good', 'timestamp': None, 'error': None},
                               'Off': {'value': False, 'quality': 'good', 'timestamp': None, 'error': None},
                               'Text': {'value': '001,设备\nΔ', 'quality': 'good', 'timestamp': None, 'error': None},
                               'Stale': {'value': 42, 'quality': 'stale', 'timestamp': None, 'error': 'Old sample'},
                               'Missing': {'value': None, 'quality': 'bad', 'timestamp': None, 'error': 'Missing tag'},
                               'Pending': {'value': None, 'quality': 'pending', 'timestamp': None, 'error': 'Waiting'}}
                    prepared = []
                    async def capture(*args):
                        response = await prepare_snapshot(*args)
                        prepared.append(response.body)
                        return response
                    path = '/api/tags' + ('?status_only=true' if status_only else '')
                    with patch.object(original.state.driver, 'sample_snapshot', return_value=deepcopy(samples)), \
                         patch('openhmi.workspace.prepare_snapshot', side_effect=capture) as prepare:
                        task, entered, release = self.paused(workspace, path, phase)
                        await asyncio.wait_for(entered.wait(), 10)
                        self.assertFalse(workspace.lock.locked())
                        subscription = await asyncio.wait_for(client.post('/api/subscriptions', json={'client': 'readout-viewer', 'screens': ['overview'], 'sequence': 1}), 10)
                        self.assertEqual(subscription.status_code, 200, subscription.text)
                        self.assertIn('readout-viewer', original.state.driver.leases)
                        self.assertEqual((await client.get('/api/project')).status_code, 200)
                        switched = await asyncio.wait_for(client.post('/api/workspace/open', json={'file': 'Candidate.openhmi.sqlite3'}), 10)
                        self.assertEqual(switched.status_code, 200, switched.text)
                        self.assert_closed(original)
                        candidate = workspace.current
                        await asyncio.wait_for(workspace._shutdown(), 10)
                        self.assert_closed(candidate)
                        self.assertFalse(task.done())
                        release.set()
                        response = await asyncio.wait_for(task, 10)
                        prepare.assert_awaited_once()
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.content, prepared[0])
                    self.assertEqual(response.headers['x-openhmi-project'], original.state.project_instance)
                    self.assertEqual(response.headers['cache-control'], 'no-store')
                    self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
                    self.assertEqual(int(response.headers['content-length']), len(response.content))
                    data = response.json()
                    if status_only:
                        self.assertNotIn('samples', data); self.assertNotIn('values', data)
                    else:
                        self.assertEqual(data['samples'], samples)
                        self.assertEqual(data['values'], {'Zero': 0, 'Off': False, 'Text': '001,设备\nΔ'})
                    frames.append({'data': data, 'statusOnly': status_only})
        from tests.test_frontend_contract import frontend
        results = frontend('tag_snapshots', snapshots=frames)['results']
        self.assertTrue(all(row['valid'] for row in results))
        self.assertEqual(results[0]['normalized']['samples'], frames[0]['data']['samples'])

    async def test_cancelled_preparation_finishes_sync_projection_before_switch_closes_runtime(self):
        workspace, original, client = await self.fixture()
        project = original.state.driver.status
        loop = asyncio.get_running_loop()
        entered, release = asyncio.Event(), Event()
        order = []
        def blocked(*, include_groups=True):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(20): raise RuntimeError('Offline test did not release projection')
            data = project(include_groups=include_groups)
            order.append('projection finished')
            return data
        close = original.state.store.close
        def close_source():
            self.assertEqual(order, ['projection finished'])
            close(); order.append('source closed')
        original.state.store.close = close_source
        follower = None
        with patch.object(original.state.driver, 'status', side_effect=blocked) as invoke:
            task = asyncio.create_task(client.get('/api/tags'))
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
        self.assertEqual(order, ['projection finished', 'source closed'])
        self.assert_closed(original)

    async def test_send_cancellation_disconnect_never_repeat_projection_or_retire_active_runtime(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                workspace, original, client = await self.fixture()
                with patch('openhmi.workspace.prepare_snapshot', wraps=prepare_snapshot) as prepare:
                    task, entered, release = self.paused(workspace, '/api/tags', 'http.response.body', fail=fail)
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
                self.assertEqual((await client.get('/api/project')).status_code, 200)
                original.state.driver.factory.assert_not_called()

    async def test_query_validation_and_sanitized_projection_failure_keep_context_and_recover(self):
        workspace, original, client = await self.fixture()
        bad_query = await client.get('/api/tags?status_only=invalid')
        self.assertEqual(bad_query.status_code, 422)
        with patch.object(original.state.driver, 'status', side_effect=RuntimeError('Private projection marker')), self.assertLogs(level='ERROR'):
            failed = await client.get('/api/tags')
        self.assertEqual(failed.status_code, 503)
        self.assertNotIn('Private projection marker', failed.text)
        for response in (bad_query, failed):
            self.assertEqual(response.headers['x-openhmi-project'], original.state.project_instance)
            self.assertEqual(response.headers['cache-control'], 'no-store')
        recovered = await client.get('/api/tags')
        self.assertEqual(recovered.status_code, 200)
        self.assertIn('samples', recovered.json())
        await workspace._shutdown()
        with patch.object(original.state.driver, 'sample_snapshot') as samples, patch.object(original.state.driver, 'status') as status:
            stopped = await client.get('/api/tags')
            self.assertEqual(stopped.status_code, 503)
            samples.assert_not_called(); status.assert_not_called()

    async def test_finite_asgi_capture_retains_fragmented_bytes_duplicate_headers_and_completion(self):
        finished = []
        headers = [(b'content-type', b'application/json'), (b'set-cookie', b'a=1'), (b'set-cookie', b'b=2')]
        async def app(scope, receive, send):
            await send({'type': 'http.response.start', 'status': 200, 'headers': headers})
            await send({'type': 'http.response.body', 'body': b'{"value":', 'more_body': True})
            await send({'type': 'http.response.body', 'body': b'0}'})
            headers.clear()
            finished.append(True)
        response = await prepare_snapshot(app, {}, None)
        self.assertEqual(finished, [True])
        self.assertEqual(json.loads(response.body), {'value': 0})
        self.assertEqual(response.headers.getlist('set-cookie'), ['a=1', 'b=2'])
        for messages in ([{'type': 'http.response.start', 'status': 200}],
                         [{'type': 'http.response.body', 'body': b'no start'}],
                         [{'type': 'http.response.start', 'status': 200, 'trailers': True}]):
            async def broken(scope, receive, send):
                for message in messages: await send(message)
            with self.assertRaises(RuntimeError): await prepare_snapshot(broken, {}, None)
