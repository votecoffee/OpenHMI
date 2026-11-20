"""Runtime resource ownership during assembly, startup and orderly shutdown."""

import asyncio
from contextlib import contextmanager, asynccontextmanager
import logging


class RuntimeLifecycle:
    def __init__(self):
        self.store = self.driver = self.trends = self.publisher = None
        self.workers = self.sample_alarms = None

    def cleanup(self, *, stop_identity=True):
        # Resolve methods now so runtime instrumentation/replacements remain visible.
        # Workers must have stopped before resources used by their callbacks close.
        for name, resource, method in (
            ('trends', self.trends, 'shutdown'), ('identity', self.publisher, 'shutdown'),
            ('acquisition', self.driver, 'close'), ('project store', self.store, 'close'),
        ):
            # Assembly has not published identity; do not introduce PLC writes.
            if resource is not None and (name != 'identity' or stop_identity):
                try:
                    getattr(resource, method)()
                except Exception:
                    logging.exception('Runtime cleanup failed for %s', name)

    @contextmanager
    def building(self):
        try:
            yield
        except BaseException:
            self.cleanup(stop_identity=False)
            raise

    @asynccontextmanager
    async def lifespan(self, app):
        workers_started = False
        try:
            await asyncio.to_thread(self.sample_alarms)
            workers_started = True
            async with self.workers.running():
                yield
        finally:
            await asyncio.to_thread(self.cleanup, stop_identity=workers_started)
