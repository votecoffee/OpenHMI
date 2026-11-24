"""Offline alarm snapshot delivery across acknowledgement and project switching."""
import asyncio
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import Mock, patch

from httpx import ASGITransport, AsyncClient
from openhmi.http_snapshot import prepare_snapshot
from openhmi.project_models import AlarmDefinition, Project, RevisionRequest, SaveRequest
from openhmi.workspace import ProjectWorkspace

PATH = '/api/alarms'
RECOVERY = '1. Inspect the synthetic sensor\n2. Restore the fixture condition\n3. Verify the indication'


class AlarmDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def fixture(self):
        directory = self.enterContext(TemporaryDirectory())
        workspace = ProjectWorkspace(Path(directory) / 'Original.openhmi.sqlite3', hold_connections=True)
        workspace.create('Candidate', 'Candidate machine')
        original = workspace.current
        original.state.driver.factory = Mock(side_effect=AssertionError('Offline test cannot contact a PLC'))
        project = Project.model_validate(original.state.store.snapshot()['active'])
        project.alarms = [AlarmDefinition(id='fixture_' + str(priority), tag='ProcessAlarm', priority=priority,
            message='设备 fixture ' + str(priority), cause='Synthetic sensor condition', response=RECOVERY) for priority in (1, 2)]
        saved = original.state.store.save(SaveRequest(expected_revision=1, project=project))
        original.state.store.apply(RevisionRequest(expected_revision=saved['draft_revision']))
        values = {'ProcessAlarm': True}
        original.state.alarms.sample_values = lambda: values.copy()
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
        return workspace, original, self.client(workspace), values

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
                    if fail: raise OSError('Synthetic disconnected alarm viewer')
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

    async def test_slow_headers_body_preserve_occurrences_quality_help_while_ack_and_switch_proceed(self):
        frames = []
        for phase in ('http.response.start', 'http.response.body'):
            with self.subTest(phase=phase):
                workspace, original, client, values = await self.fixture()
                monitor = original.state.alarms
                values['ProcessAlarm'] = None
                monitor.sample()
                prepared = []
                async def capture(*args):
                    response = await prepare_snapshot(*args)
                    if args[1]['path'] == PATH: prepared.append(response.body)
                    return response
                with patch('openhmi.workspace.prepare_snapshot', side_effect=capture):
                    task, entered, release = self.paused(workspace, phase)
                    await asyncio.wait_for(entered.wait(), 10)
                    self.assertFalse(workspace.lock.locked())
                    expected = json.loads(prepared[0])
                    self.assertEqual((expected['active_count'], expected['unacknowledged_count']), (2, 2))
                    self.assertEqual({state['quality'] for state in expected['states'].values()}, {'bad'})
                    self.assertTrue(all(row['response'] == RECOVERY for row in expected['outstanding']))
                    self.assertTrue(all(row['responses']['en'] == RECOVERY for row in expected['outstanding']))
                    identifier = min(row['occurrence_id'] for row in expected['outstanding'])
                    self.assertEqual((await client.get('/api/tags')).status_code, 200)
                    with patch.object(monitor, 'acknowledge', wraps=monitor.acknowledge) as acknowledge:
                        ack = await asyncio.wait_for(client.post(f'{PATH}/{identifier}/acknowledge', json={'comment': 'Synthetic recovery steps reviewed'}), 10)
                        self.assertEqual(ack.status_code, 200, ack.text)
                        self.assertEqual(ack.json()['acknowledged'], [identifier])
                        acknowledge.assert_called_once()
                        operation = ack.headers['x-openhmi-operation-id']
                        self.assertEqual(ack.headers['x-openhmi-audit-status'], 'succeeded')
                        with original.state.store._lock:
                            row = original.state.store._db.execute('SELECT operation_id,comment FROM alarm_acknowledgement WHERE occurrence_id=?', (identifier,)).fetchone()
                            self.assertEqual(row, (operation, 'Synthetic recovery steps reviewed'))
                            self.assertEqual(original.state.store._db.execute('SELECT status FROM operator_activity WHERE operation_id=?', (operation,)).fetchone(), ('succeeded',))
                            self.assertEqual(original.state.store._db.execute("SELECT COUNT(*) FROM alarm_event WHERE occurrence_id=? AND event='acknowledged'", (identifier,)).fetchone()[0], 1)
                        newer = (await client.get(PATH)).json()
                        self.assertEqual(newer['unacknowledged_count'], 1)
                    switched = await asyncio.wait_for(client.post('/api/workspace/open', json={'file': 'Candidate.openhmi.sqlite3'}), 10)
                    self.assertEqual(switched.status_code, 200, switched.text)
                    self.assert_closed(original)
                    candidate = workspace.current
                    candidate.state.alarms.sample_values = lambda: {'ProcessAlarm': True}
                    candidate.state.alarms.sample()
                    collision = candidate.state.alarms.snapshot()['outstanding'][0]['occurrence_id']
                    self.assertEqual(collision, identifier)
                    with patch.object(candidate.state.alarms, 'acknowledge', side_effect=AssertionError('Old project cannot acknowledge')) as acknowledge, \
                         patch.object(candidate.state.activity, 'run', side_effect=AssertionError('Stale request cannot start journal operation')) as journal:
                        stale = await client.post(f'{PATH}/{collision}/acknowledge', json={}, headers={'X-OpenHMI-Project': original.state.project_instance})
                        self.assertEqual(stale.status_code, 409)
                        acknowledge.assert_not_called(); journal.assert_not_called()
                    await asyncio.wait_for(workspace._shutdown(), 10)
                    self.assert_closed(candidate)
                    self.assertFalse(task.done())
                    release.set()
                    response = await asyncio.wait_for(task, 10)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, prepared[0])
                self.assertEqual(response.json(), expected)
                self.assertEqual(response.headers['x-openhmi-project'], original.state.project_instance)
                self.assertEqual(response.headers['cache-control'], 'no-store')
                self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
                self.assertEqual(int(response.headers['content-length']), len(response.content))
                frames += [response.json(), newer]
        from tests.test_frontend_contract import frontend
        self.assertEqual(frontend('alarm_snapshots', snapshots=frames)['valid'], [True] * len(frames))

    async def test_cancelled_alarm_preparation_drains_before_queued_switch_closes_store(self):
        workspace, original, client, _ = await self.fixture()
        snapshot = original.state.alarms.snapshot
        loop = asyncio.get_running_loop()
        entered, release = asyncio.Event(), Event()
        order = []
        def blocked():
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(20): raise RuntimeError('Offline test did not release alarm snapshot')
            result = snapshot()
            order.append('snapshot finished')
            return result
        close = original.state.store.close
        def close_source():
            self.assertEqual(order, ['snapshot finished'])
            close(); order.append('source closed')
        original.state.store.close = close_source
        follower = None
        with patch.object(original.state.alarms, 'snapshot', side_effect=blocked) as invoke:
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

    async def test_send_cancellation_disconnect_never_repeat_snapshot_acknowledge_or_journal(self):
        for fail in (False, True):
            with self.subTest(fail=fail):
                workspace, original, client, _ = await self.fixture()
                with patch('openhmi.workspace.prepare_snapshot', wraps=prepare_snapshot) as prepare, \
                     patch.object(original.state.alarms, 'acknowledge') as acknowledge, patch.object(original.state.activity, 'run') as journal:
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
                    acknowledge.assert_not_called(); journal.assert_not_called()
                self.assertFalse(workspace.lock.locked())
                self.assertIs(workspace.current, original)
                self.assertEqual((await client.get(PATH)).status_code, 200)
                original.state.driver.factory.assert_not_called()

    async def test_alarm_failure_is_sanitized_recoverable_and_shutdown_rejects_closed_monitor(self):
        workspace, original, client, _ = await self.fixture()
        with patch.object(original.state.alarms, 'snapshot', side_effect=RuntimeError('Private alarm DB marker')), self.assertLogs(level='ERROR'):
            failed = await client.get(PATH)
        self.assertEqual(failed.status_code, 503)
        self.assertNotIn('Private alarm DB marker', failed.text)
        self.assertEqual(failed.headers['x-openhmi-project'], original.state.project_instance)
        self.assertEqual(failed.headers['cache-control'], 'no-store')
        self.assertEqual((await client.get(PATH)).status_code, 200)
        await workspace._shutdown()
        with patch.object(original.state.alarms, 'snapshot') as snapshot:
            stopped = await client.get(PATH)
            self.assertEqual(stopped.status_code, 503)
            snapshot.assert_not_called()
