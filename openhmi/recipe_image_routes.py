"""Recipe image HTTP boundaries; decoding, storage and policy stay in the service."""

from fastapi import HTTPException, Request, Response, Query


def add_recipe_image_routes(app, service, user, invoke):
    @app.get('/api/recipe-images/{image_id}')
    def image(image_id: str):
        return Response(invoke(service.image, image_id), media_type='image/png', headers={'Cache-Control': 'public,max-age=31536000,immutable', 'X-Content-Type-Options': 'nosniff'})

    @app.post('/api/recipe-images')
    async def upload_image(request: Request, reason: str = Query(min_length=1, max_length=1000)):
        current = user(request)
        if not current.permits('engineer'):
            raise HTTPException(403, 'Recipe engineer role is required')
        if request.headers.get('content-type', '').split(';')[0] not in ('image/png', 'image/jpeg'):
            raise HTTPException(415, 'Upload a PNG or JPEG image')
        if not reason.strip():
            raise HTTPException(422, 'A meaningful image change reason is required')
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 5 * 1024 * 1024:
                raise HTTPException(413, 'Recipe image upload exceeds 5 MiB')
        return invoke(service.add_image, bytes(data), reason, current)
