"""HTTP registration for project-owned canvas images."""

from fastapi import HTTPException, Query, Request, Response


def add_canvas_routes(app, images, security):
    from .canvas import MAX_IMAGE

    @app.post('/api/canvas-images')
    async def upload(request: Request, name: str = Query(default='', max_length=512)):
        from starlette.concurrency import run_in_threadpool

        security.require(request, 'project.edit')
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_IMAGE:
                raise HTTPException(413, 'Canvas image exceeds 8 MiB')
            data.extend(chunk)
        try:
            return {'id': await run_in_threadpool(images.put, data, name)}
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.get('/api/canvas-images')
    def list_images(request: Request, before: int | None = Query(default=None, ge=1, le=9223372036854775807),
                    limit: int = Query(default=12, ge=1, le=32), search: str = Query(default='', max_length=100)):
        security.require(request, 'project.edit')
        return images.list(before, limit, search)

    @app.get('/api/canvas-images/{identifier}')
    def image(identifier: str):
        result = images.get(identifier)
        if not result:
            raise HTTPException(404, 'Background image not found')
        media_type, data = result
        return Response(data, media_type=media_type, headers={'Cache-Control': 'private, max-age=86400',
                                                             'X-Content-Type-Options': 'nosniff'})
