"""Prepare a finite ASGI response without owning runtime resources during delivery."""
from starlette.responses import Response


async def prepare_snapshot(app, scope, receive):
    status, headers, complete = None, None, False
    parts = []

    async def capture(message):
        nonlocal status, headers, complete
        if message['type'] == 'http.response.start' and status is None:
            status = message['status']
            if type(status) is not int or not 100 <= status <= 599 or message.get('trailers'):
                raise RuntimeError('Unsupported snapshot response start')
            headers = [(bytes(name), bytes(value)) for name, value in message.get('headers', [])]
        elif message['type'] == 'http.response.body' and status is not None and not complete:
            body = message.get('body', b'')
            if not isinstance(body, bytes):
                raise RuntimeError('Snapshot response body must be bytes')
            if body:
                parts.append(body)  # Keep the already encoded, immutable bytes.
            complete = not message.get('more_body', False)
        else:
            raise RuntimeError('Unsupported snapshot response framing')

    await app(scope, receive, capture)
    if status is None or not complete:
        raise RuntimeError('Incomplete snapshot response')
    response = Response(b''.join(parts), status_code=status)
    response.raw_headers = headers
    return response
