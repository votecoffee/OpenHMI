"""Bounded async startup/cancellation tests; no network or controller access."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import sqlite3
import unittest
from unittest.mock import Mock, patch

from openhmi.runtime_workers import RuntimeWorkers
from openhmi.server import create_app


class WorkerStartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_task_creation_drains_created_tasks_and_closes_unscheduled_coroutine(self):
        for fail_at in (1, 2, 3):
            with self.subTest(fail_at=fail_at):
                callbacks = Mock()
                workers = RuntimeWorkers({name: (0.01, callbacks) for name in ('first', 'second', 'third')})
                original = asyncio.create_task
                created, rejected, pools = [], [], []
                failure = RuntimeError('Offline scheduler allocation failure')
                attempts = 0
                def create(coroutine, **kwargs):
                    nonlocal attempts
                    attempts += 1
                    if attempts == fail_at:
                        rejected.append(coroutine)
                        raise failure
                    task = original(coroutine, **kwargs)
                    created.append(task)
                    return task
                def pool(**kwargs):
                    instance = ThreadPoolExecutor(**kwargs)
                    instance.shutdown = Mock(wraps=instance.shutdown)
                    pools.append(instance)
                    return instance
                with patch('openhmi.runtime_workers.asyncio.create_task', side_effect=create), \
                     patch('openhmi.runtime_workers.ThreadPoolExecutor', side_effect=pool):
                    with self.assertRaises(RuntimeError) as raised:
                        async with workers.running():
                            self.fail('Partial startup cannot yield a running context')
                self.assertIs(raised.exception, failure)
                self.assertTrue(all(task.done() for task in created))
                self.assertEqual(len(created), fail_at - 1)
                self.assertIsNone(rejected[0].cr_frame)
                callbacks.assert_not_called()
                pools[0].shutdown.assert_called_once_with(wait=True)
                self.assertTrue(all(item['state'] == 'stopped' for item in workers.snapshot()[:fail_at - 1]))

    async def test_partial_worker_startup_drains_before_real_app_resources_close(self):
        app = create_app()
        app.state.driver.factory = Mock(side_effect=AssertionError('Offline test cannot open a PLC connection'))
        original_create = asyncio.create_task
        created = []
        failure = RuntimeError('Offline third worker failed to schedule')
        attempts = 0
        def create(coroutine, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 3:
                raise failure
            task = original_create(coroutine, **kwargs)
            created.append(task)
            return task
        close_store = app.state.store.close
        def close():
            self.assertTrue(all(task.done() for task in created))
            close_store()
        app.state.store.close = Mock(side_effect=close)
        with patch('openhmi.runtime_workers.asyncio.create_task', side_effect=create):
            with self.assertRaises(RuntimeError) as raised:
                async with app.router.lifespan_context(app):
                    self.fail('Failed startup cannot serve requests')
        self.assertIs(raised.exception, failure)
        app.state.store.close.assert_called_once()
        with self.assertRaises(sqlite3.ProgrammingError):
            app.state.store._db.execute('SELECT 1')
        app.state.driver.factory.assert_not_called()

    async def test_repeated_cancellation_waits_for_active_callback_and_executor(self):
        for cancel_scheduler in (False, True):
            with self.subTest(cancel_scheduler=cancel_scheduler):
                loop = asyncio.get_running_loop()
                entered, draining, joining = asyncio.Event(), asyncio.Event(), asyncio.Event()
                release = Event()
                finished = Event()
                created = []
                def callback():
                    loop.call_soon_threadsafe(entered.set)
                    if not release.wait(5):
                        raise RuntimeError('Offline test failed to release its callback')
                    finished.set()
                workers = RuntimeWorkers({'fixture': (0.01, callback)})
                original_drain = workers._drain
                async def drain(*args):
                    draining.set()
                    await original_drain(*args)
                workers._drain = drain
                def pool(**kwargs):
                    instance = ThreadPoolExecutor(**kwargs)
                    shutdown = instance.shutdown
                    def join(**options):
                        loop.call_soon_threadsafe(joining.set)
                        shutdown(**options)
                    instance.shutdown = join
                    return instance
                original_create = asyncio.create_task
                def create(coroutine, **kwargs):
                    task = original_create(coroutine, **kwargs)
                    created.append(task)
                    return task
                async def owner():
                    async with workers.running():
                        await asyncio.Event().wait()
                with patch('openhmi.runtime_workers.ThreadPoolExecutor', side_effect=pool), \
                     patch('openhmi.runtime_workers.asyncio.create_task', side_effect=create):
                    task = original_create(owner())
                    try:
                        await asyncio.wait_for(entered.wait(), 2)
                        if cancel_scheduler:
                            created[0].cancel()
                        task.cancel()
                        await asyncio.wait_for(draining.wait(), 2)
                        if cancel_scheduler:
                            await asyncio.wait_for(joining.wait(), 2)
                        task.cancel()  # Repeated cancellation cannot detach cleanup.
                        await asyncio.sleep(0)
                        self.assertFalse(task.done())
                        self.assertFalse(finished.is_set())
                    finally:
                        release.set()
                        with self.assertRaises(asyncio.CancelledError):
                            await asyncio.wait_for(asyncio.shield(task), 2)
                self.assertTrue(finished.is_set())
                self.assertTrue(all(item.done() for item in created))
                self.assertEqual(workers.snapshot()[0]['state'], 'stopped')
                self.assertTrue(joining.is_set())

    async def test_repeated_cancellation_does_not_detach_resource_cleanup(self):
        app = create_app()
        app.state.driver.factory = Mock(side_effect=AssertionError('Offline test cannot open a PLC connection'))
        loop = asyncio.get_running_loop()
        ready, cleaning = asyncio.Event(), asyncio.Event()
        release = Event()
        order = []
        original_trends = app.state.trends.shutdown
        def trends():
            self.assertTrue(all(item['state'] == 'stopped' for item in app.state.runtime_workers.snapshot()))
            loop.call_soon_threadsafe(cleaning.set)
            if not release.wait(5):
                raise RuntimeError('Offline test failed to release cleanup')
            original_trends()
            order.append('trends')
        app.state.trends.shutdown = trends
        for resource, method, name in [(app.state.identity_publisher, 'shutdown', 'identity'),
            (app.state.driver, 'close', 'acquisition'), (app.state.store, 'close', 'store')]:
            original = getattr(resource, method)
            def cleanup(original=original, name=name):
                original()
                order.append(name)
            setattr(resource, method, cleanup)
        async def owner():
            async with app.router.lifespan_context(app):
                ready.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(owner())
        try:
            await asyncio.wait_for(ready.wait(), 2)
            task.cancel()
            await asyncio.wait_for(cleaning.wait(), 2)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            self.assertEqual(order, [])
        finally:
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(task), 2)
        self.assertEqual(order, ['trends', 'identity', 'acquisition', 'store'])
        app.state.driver.factory.assert_not_called()

    async def test_cancelled_initial_sample_finishes_before_resources_close(self):
        app = create_app()
        app.state.driver.factory = Mock(side_effect=AssertionError('Offline test cannot open a PLC connection'))
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        release, finished = Event(), Event()
        original_sample = app.state.alarms.sample
        def sample():
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise RuntimeError('Offline test did not release initial sample')
            original_sample()
            finished.set()
        app.state.alarms.sample = sample
        original_close = app.state.store.close
        def close():
            self.assertTrue(finished.is_set())
            original_close()
        app.state.store.close = Mock(side_effect=close)
        app.state.identity_publisher.shutdown = Mock()
        app.state.runtime_workers.running = Mock()
        async def owner():
            async with app.router.lifespan_context(app):
                self.fail('Cancelled startup cannot yield')
        task = asyncio.create_task(owner())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            app.state.store.close.assert_not_called()
        finally:
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(task), 2)
        self.assertTrue(finished.is_set())
        app.state.store.close.assert_called_once()
        app.state.identity_publisher.shutdown.assert_not_called()
        app.state.runtime_workers.running.assert_not_called()
        app.state.driver.factory.assert_not_called()

    async def test_unexpected_scheduler_error_is_collected_without_skipping_peer_drain(self):
        workers = RuntimeWorkers({'failed': (0.01, lambda: None), 'peer': (0.01, lambda: None)})
        original = workers._run
        failed = asyncio.Event()
        async def run(name, *args):
            if name == 'failed':
                failed.set()
                raise RuntimeError('Offline unexpected scheduler error')
            await original(name, *args)
        workers._run = run
        with self.assertLogs(level='ERROR') as logs:
            async with workers.running():
                await asyncio.wait_for(failed.wait(), 2)
        self.assertTrue(any('Runtime worker failed stopped unexpectedly' in line for line in logs.output))
        self.assertEqual(workers.snapshot()[1]['state'], 'stopped')
