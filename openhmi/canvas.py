"""Freeform screen coordinates and project-owned background images."""

import hashlib
from io import BytesIO
from typing import Literal

from fastapi import HTTPException, Request, Response
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_IMAGE = 8 * 1024 * 1024
MAX_PROJECT_IMAGES = 48 * 1024 * 1024


class CanvasBox(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    x: int = Field(ge=0, le=4096)
    y: int = Field(ge=0, le=4096)
    width: int = Field(ge=32, le=4096)
    height: int = Field(ge=24, le=4096)
    z: int = Field(default=0, ge=0, le=9999)
    group: str = Field(default='', max_length=100)


class CanvasContainer(CanvasBox):
    mode: Literal['grid', 'stack']
    columns: int = Field(default=2, ge=1, le=8)
    members: list[str] = Field(default_factory=list, max_length=100)


class CanvasLayout(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    width: int = Field(default=1024, ge=160, le=4096)
    height: int = Field(default=640, ge=120, le=4096)
    grid: int = Field(default=8, ge=2, le=100)
    snap: bool = True
    background: str = Field(default='', pattern=r'^(?:[a-f0-9]{64})?$')
    boxes: dict[str, CanvasBox] = Field(default_factory=dict, max_length=100)
    containers: dict[str, CanvasContainer] = Field(default_factory=dict, max_length=30)

    @model_validator(mode='after')
    def consistent(self):
        if self.boxes.keys() & self.containers.keys():
            raise ValueError('Control and container IDs must be distinct')
        members = [member for container in self.containers.values() for member in container.members]
        if len(members) != len(set(members)) or set(members) - self.boxes.keys():
            raise ValueError('A control can belong to one canvas container')
        for box in (*self.boxes.values(), *self.containers.values()):
            if box.x + box.width > self.width or box.y + box.height > self.height:
                raise ValueError('Canvas objects must fit within the screen')
        return self


class CanvasImages:
    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS canvas_image (
                id TEXT PRIMARY KEY, media_type TEXT NOT NULL, data BLOB NOT NULL
            )''')

    def put(self, raw):
        try:
            with Image.open(BytesIO(raw), formats=['PNG', 'JPEG', 'WEBP']) as image:
                if max(image.size) > 4096 or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('Use a single image no larger than 4096 pixels per side')
                result = ImageOps.exif_transpose(image).convert('RGBA')
                result.info.clear()
                encoded = BytesIO()
                result.save(encoded, format='WEBP', quality=88, method=4)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
            raise ValueError('Use a valid PNG, JPEG or WebP image') from error
        data = encoded.getvalue()
        if len(data) > MAX_IMAGE:
            raise ValueError('Encoded background image exceeds 8 MiB')
        identifier = hashlib.sha256(data).hexdigest()
        with self.store.transaction() as db:
            if db.execute('SELECT 1 FROM canvas_image WHERE id=?', (identifier,)).fetchone():
                return identifier
            total = db.execute('SELECT COALESCE(SUM(length(data)),0) FROM canvas_image').fetchone()[0]
            if total + len(data) > MAX_PROJECT_IMAGES:
                raise ValueError('Project background images exceed the 48 MiB storage budget')
            db.execute('INSERT INTO canvas_image VALUES (?, ?, ?)', (identifier, 'image/webp', data))
        return identifier

    def get(self, identifier):
        with self.store._lock:
            return self.store._db.execute('SELECT media_type,data FROM canvas_image WHERE id=?', (identifier,)).fetchone()

    def validate(self, project):
        identifiers = {layout.background for layout in [project.layout, *(screen.layout for screen in project.screens)]
                       if layout and layout.background}
        with self.store._lock:
            for identifier in identifiers:
                if not self.store._db.execute('SELECT 1 FROM canvas_image WHERE id=?', (identifier,)).fetchone():
                    raise HTTPException(422, 'Screen references a background image missing from this project')


def add_canvas_routes(app, images, security):
    @app.post('/api/canvas-images')
    async def upload(request: Request):
        from starlette.concurrency import run_in_threadpool

        security.require(request, 'project.edit')
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_IMAGE:
                raise HTTPException(413, 'Background image exceeds 8 MiB')
            data.extend(chunk)
        try:
            return {'id': await run_in_threadpool(images.put, data)}
        except ValueError as error:
            raise HTTPException(422, str(error)) from error

    @app.get('/api/canvas-images/{identifier}')
    def image(identifier: str):
        result = images.get(identifier)
        if not result:
            raise HTTPException(404, 'Background image not found')
        media_type, data = result
        return Response(data, media_type=media_type, headers={'Cache-Control': 'private, max-age=86400',
                                                             'X-Content-Type-Options': 'nosniff'})
