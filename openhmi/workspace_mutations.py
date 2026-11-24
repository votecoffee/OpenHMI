"""Small project create/open requests: bounded receipt, serialized dispatch."""
import asyncio
import json

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from .async_cleanup import finish_cleanup
from .http_context import require_project_instance, set_response_context
from .workspace_contracts import OpenedProject

MAX_REQUEST = 4096
RECEIVE_SECONDS = 30


async def read_request(request):
    data = bytearray()
    try:
        async with asyncio.timeout(RECEIVE_SECONDS):
            async for chunk in request.stream():
                if len(chunk) > MAX_REQUEST - len(data):
                    raise HTTPException(413, 'Request too large')
                data.extend(chunk)
    except TimeoutError as error:
        raise HTTPException(408, 'Project request timed out before completion; no operation was started.') from error
    except ClientDisconnect as error:
        raise HTTPException(400, 'Project request disconnected before completion; no operation was started.') from error
    return data


async def mutation_response(workspace, request):
    admitted = False
    try:
        async with workspace.lock:
            identifier = workspace.current.state.project_instance
            require_project_instance(request, identifier)
            if workspace.stopping:
                raise HTTPException(503, 'The workspace is stopping; no operation was started.')
            workspace.require_management(request)
            if workspace.mutation_slots.locked():
                raise HTTPException(429, 'Too many project requests are pending. Wait before retrying explicitly.')
            await workspace.mutation_slots.acquire()
            admitted = True
        raw = await read_request(request)
        async with workspace.lock:
            if workspace.stopping:
                raise HTTPException(503, 'The workspace stopped while receiving the request; no operation was started.')
            if workspace.current.state.project_instance != identifier:
                raise HTTPException(409, 'A different project was opened while receiving the request. Reload before trying again; no operation was started.')
            require_project_instance(request, identifier)
            workspace.require_management(request)
            try:
                body = json.loads(raw)
            except (ValueError, UnicodeDecodeError, RecursionError) as error:
                raise HTTPException(422, 'Invalid request') from error
            if not isinstance(body, dict):
                raise HTTPException(422, 'Invalid request')
            if request.url.path.endswith('/create'):
                result = await finish_cleanup(asyncio.to_thread(workspace.create, body.get('name', ''), body.get('title', '')))
            else:
                await workspace.open(body.get('file', ''))
                result = OpenedProject(ok=True, current=workspace.path.name).model_dump()
            response = JSONResponse(result)
    except HTTPException as error:
        response = JSONResponse({'detail': error.detail}, status_code=error.status_code)
    finally:
        if admitted:
            workspace.mutation_slots.release()
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return set_response_context(request, response, identifier)
