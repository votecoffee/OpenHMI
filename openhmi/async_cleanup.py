"""Await owned cleanup to completion before propagating caller cancellation."""

import asyncio


async def finish_cleanup(awaitable):
    task = asyncio.ensure_future(awaitable)
    cancelled = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as error:
            if task.cancelled():
                raise
            cancelled = error
    result = task.result()
    if cancelled is not None:
        raise cancelled
    return result
