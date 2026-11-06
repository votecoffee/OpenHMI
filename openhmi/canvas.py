"""Freeform screen coordinates and project-owned background images."""

import hashlib
from io import BytesIO
from typing import Literal

from fastapi import HTTPException, Query, Request, Response
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


class CanvasDecoration(CanvasBox):
    kind: Literal['image', 'rectangle', 'ellipse']
    label: str = Field(min_length=1, max_length=100)
    locked: bool = False
    image: str = Field(default='', pattern=r'^(?:[a-f0-9]{64})?$')
    fill: str = Field(default='#aaaaaa', pattern=r'^#[a-fA-F0-9]{6}$')

    @model_validator(mode='after')
    def valid_decoration(self):
        if (self.kind == 'image') != bool(self.image):
            raise ValueError('Only image objects require an image reference')
        if self.locked and self.group:
            raise ValueError('Locked background objects cannot belong to a group')
        return self


class CanvasLayout(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    width: int = Field(default=1024, ge=160, le=4096)
    height: int = Field(default=640, ge=120, le=4096)
    grid: int = Field(default=8, ge=2, le=100)
    snap: bool = True
    background: str = Field(default='', pattern=r'^(?:[a-f0-9]{64})?$')
    boxes: dict[str, CanvasBox] = Field(default_factory=dict, max_length=100)
    containers: dict[str, CanvasContainer] = Field(default_factory=dict, max_length=30)
    decorations: dict[str, CanvasDecoration] = Field(default_factory=dict, max_length=60)

    @model_validator(mode='after')
    def consistent(self):
        keys = [*self.boxes, *self.containers, *self.decorations]
        if len(keys) != len(set(keys)):
            raise ValueError('Canvas object IDs must be distinct')
        members = [member for container in self.containers.values() for member in container.members]
        if len(members) != len(set(members)) or set(members) - self.boxes.keys():
            raise ValueError('A control can belong to one canvas container')
        for box in (*self.boxes.values(), *self.containers.values(), *self.decorations.values()):
            if box.x + box.width > self.width or box.y + box.height > self.height:
                raise ValueError('Canvas objects must fit within the screen')
        return self


class CanvasImages:
    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS canvas_image (
                id TEXT PRIMARY KEY, media_type TEXT NOT NULL, data BLOB NOT NULL, name TEXT NOT NULL DEFAULT ''
            )''')
            if 'name' not in {column[1] for column in db.execute('PRAGMA table_info(canvas_image)')}:
                db.execute("ALTER TABLE canvas_image ADD COLUMN name TEXT NOT NULL DEFAULT ''")

    def put(self, raw, name=''):
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
            raise ValueError('Encoded canvas image exceeds 8 MiB')
        identifier = hashlib.sha256(data).hexdigest()
        filename = name.replace('\\', '/').rsplit('/', 1)[-1]
        filename = ''.join(character for character in filename if character.isprintable()).strip()[:100]
        with self.store.transaction() as db:
            if db.execute('SELECT 1 FROM canvas_image WHERE id=?', (identifier,)).fetchone():
                if filename:
                    db.execute("UPDATE canvas_image SET name=? WHERE id=? AND name=''", (filename, identifier))
                return identifier
            total = db.execute('SELECT COALESCE(SUM(length(data)),0) FROM canvas_image').fetchone()[0]
            if total + len(data) > MAX_PROJECT_IMAGES:
                raise ValueError('Project canvas images exceed the 48 MiB storage budget')
            db.execute('INSERT INTO canvas_image(id, media_type, data, name) VALUES (?, ?, ?, ?)',
                       (identifier, 'image/webp', data, filename))
        return identifier

    def list(self, before, limit):
        with self.store._lock:
            query = 'SELECT rowid, id, name FROM canvas_image'
            where, parameters = ('', ()) if before is None else (' WHERE rowid < ?', (before,))
            rows = self.store._db.execute(query + where + ' ORDER BY rowid DESC LIMIT ?',
                                          (*parameters, limit + 1)).fetchall()
        return {'items': [{'id': identifier, 'name': name} for _, identifier, name in rows[:limit]],
                'next_before': rows[limit - 1][0] if len(rows) > limit else None}

    def get(self, identifier):
        with self.store._lock:
            return self.store._db.execute('SELECT media_type,data FROM canvas_image WHERE id=?', (identifier,)).fetchone()

    def validate(self, project):
        layouts = [project.layout, *(screen.layout for screen in project.screens)]
        identifiers = {identifier for layout in layouts if layout
                       for identifier in (layout.background, *(item.image for item in layout.decorations.values()))
                       if identifier}
        for controls in (project.controls, *(screen.controls for screen in project.screens),
                         *(faceplate.controls for faceplate in project.faceplates)):
            for control in controls:
                if control.kind == 'state_image':
                    identifiers.update(identifier for identifier in (control.on_image, control.off_image) if identifier)
                if control.kind in ('image', 'position_image', 'rotation_image') and control.image:
                    identifiers.add(control.image)
                if control.kind == 'multi_state_image':
                    identifiers.update(state.image for state in control.states if state.image)
        with self.store._lock:
            for identifier in identifiers:
                if not self.store._db.execute('SELECT 1 FROM canvas_image WHERE id=?', (identifier,)).fetchone():
                    raise HTTPException(422, 'Screen references a canvas image missing from this project')


def add_canvas_routes(app, images, security):
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
                    limit: int = Query(default=12, ge=1, le=32)):
        security.require(request, 'project.edit')
        return images.list(before, limit)

    @app.get('/api/canvas-images/{identifier}')
    def image(identifier: str):
        result = images.get(identifier)
        if not result:
            raise HTTPException(404, 'Background image not found')
        media_type, data = result
        return Response(data, media_type=media_type, headers={'Cache-Control': 'private, max-age=86400',
                                                             'X-Content-Type-Options': 'nosniff'})
