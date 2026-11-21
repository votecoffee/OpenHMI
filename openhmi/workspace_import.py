"""Bounded upload receipt outside the active runtime's operation lock."""
import asyncio

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from .async_cleanup import finish_cleanup
from .http_context import require_project_instance, set_response_context

UPLOAD_SECONDS = 30


async def read_upload(request, maximum):
    data = bytearray()
    try:
        async with asyncio.timeout(UPLOAD_SECONDS):
            async for chunk in request.stream():
                if len(chunk) > maximum - len(data):
                    raise HTTPException(413, 'Backup upload exceeds 256 MiB')
                data.extend(chunk)
    except TimeoutError as error:
        raise HTTPException(408, 'Backup upload timed out before completion; no project was imported.') from error
    except ClientDisconnect as error:
        raise HTTPException(400, 'Backup upload disconnected before completion; no project was imported.') from error
    return bytes(data)


async def import_response(workspace, request, maximum):
    # Capture identity even for legacy callers without a project header. Admission
    # and dispatch each authorize against the currently owned, open runtime.
    admitted = False
    try:
        async with workspace.lock:
            identifier = workspace.current.state.project_instance
            require_project_instance(request, identifier)
            if workspace.stopping:
                raise HTTPException(503, 'The workspace is stopping; no project was imported.')
            workspace.require_management(request)
            if workspace.upload_lock.locked():
                raise HTTPException(429, 'Another backup import is in progress. Wait before retrying explicitly.')
            await workspace.upload_lock.acquire()
            admitted = True
        data = await read_upload(request, maximum)
        async with workspace.lock:
            if workspace.stopping:
                raise HTTPException(503, 'The workspace stopped during upload; no project was imported.')
            if workspace.current.state.project_instance != identifier:
                raise HTTPException(409, 'A different project was opened during upload. Reload before importing again; no project was imported.')
            require_project_instance(request, identifier)
            workspace.require_management(request)
            result = await finish_cleanup(asyncio.to_thread(workspace.import_backup, request.query_params.get('name', ''), data))
            response = JSONResponse(result)
    except HTTPException as error:
        response = JSONResponse({'detail': error.detail}, status_code=error.status_code)
    finally:
        if admitted:
            workspace.upload_lock.release()
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return set_response_context(request, response, identifier)
