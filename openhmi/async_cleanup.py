"""Await owned work to completion before propagating caller cancellation."""

import asyncio
import logging


async def finish_cleanup(awaitable):
    task = asyncio.ensure_future(awaitable)
    cancelled = None
    try:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError as error:
                if task.cancelled():
                    raise
                cancelled = error
        result = task.result()
    except Exception:
        if cancelled is None:
            raise
        logging.exception('Owned work failed while cancellation was pending')
        raise cancelled from None
    if cancelled is not None:
        raise cancelled
    return result
