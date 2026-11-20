"""Independent periodic runtime services with bounded work and health snapshots."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
from threading import Lock
import time

from .async_cleanup import finish_cleanup


def utc_stamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class RuntimeWorkers:
    def __init__(self, jobs):
        self.jobs = jobs
        self.lock = Lock()
        self.health = {
            name: {'id': name, 'state': 'starting', 'interval_seconds': interval, 'last_started_at': None,
                   'last_success_at': None, 'last_failure_at': None, 'last_error_type': None,
                   'failures': 0, 'consecutive_failures': 0, '_running_since': None, '_retry_at': None}
            for name, (interval, _) in jobs.items()
        }

    def snapshot(self):
        now = time.monotonic()
        with self.lock:
            statuses = [dict(item) for item in self.health.values()]
        for status in statuses:
            started, retry = status.pop('_running_since'), status.pop('_retry_at')
            status['running_seconds'] = round(max(0, now - started), 3) if started is not None else None
            status['retry_in_seconds'] = round(max(0, retry - now), 3) if retry is not None else None
            if status['running_seconds'] is not None and status['running_seconds'] >= 5:
                status['state'] = 'overdue'
        return statuses

    async def _run(self, name, interval, callback, pool, stopping):
        loop = asyncio.get_running_loop()
        status = self.health[name]
        try:
            while not stopping.is_set():
                with self.lock:
                    status.update(last_started_at=utc_stamp(), _running_since=time.monotonic(), _retry_at=None)
                try:
                    await loop.run_in_executor(pool, callback)
                except Exception as error:
                    with self.lock:
                        failures = status['consecutive_failures'] + 1
                        delay = min(5.0, 0.25 * 2 ** min(failures - 1, 5))
                        status.update(state='retrying', failures=status['failures'] + 1, consecutive_failures=failures,
                                      last_failure_at=utc_stamp(), last_error_type=type(error).__name__,
                                      _running_since=None, _retry_at=time.monotonic() + delay)
                    logging.exception('Runtime worker %s failed', name)
                else:
                    delay = interval
                    with self.lock:
                        status.update(state='healthy', last_success_at=utc_stamp(), consecutive_failures=0, _running_since=None)
                try:
                    await asyncio.wait_for(stopping.wait(), timeout=delay)
                except TimeoutError:
                    pass
        finally:
            with self.lock:
                status.update(state='stopped', _running_since=None, _retry_at=None)

    async def _drain(self, tasks, pool):
        try:
            if tasks:
                _, pending = await asyncio.wait(tasks, timeout=5)
                if pending:
                    logging.warning('Waiting for runtime workers to stop: %s', ', '.join(sorted(tasks[task] for task in pending)))
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for task, result in zip(tasks, results):
                    if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                        logging.error('Runtime worker %s stopped unexpectedly', tasks[task],
                                      exc_info=(type(result), result, result.__traceback__))
        finally:
            # A cancelled scheduler may still own a running synchronous callback.
            # Join off the event loop, before its database/PLC resources can close.
            await asyncio.to_thread(pool.shutdown, wait=True)

    @asynccontextmanager
    async def running(self):
        stopping = asyncio.Event()
        # Each scheduler awaits its one invocation before submitting another.
        pool = ThreadPoolExecutor(max_workers=len(self.jobs), thread_name_prefix='openhmi-runtime')
        tasks = {}
        try:
            for name, (interval, callback) in self.jobs.items():
                coroutine = self._run(name, interval, callback, pool, stopping)
                try:
                    task = asyncio.create_task(coroutine)
                except BaseException:
                    coroutine.close()
                    raise
                tasks[task] = name
            yield
        finally:
            stopping.set()
            # Partial startup and repeated caller cancellation must still drain
            # every created task and its executor before lifespan cleanup starts.
            await finish_cleanup(self._drain(tasks, pool))
