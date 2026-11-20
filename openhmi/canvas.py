"""Freeform screen coordinates and project-owned background images."""

import hashlib
from io import BytesIO

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from .canvas_models import CanvasBox, CanvasContainer, CanvasDecoration, CanvasLayout  # compatibility exports

MAX_IMAGE = 8 * 1024 * 1024
MAX_PROJECT_IMAGES = 48 * 1024 * 1024


class CanvasImages:
    def __init__(self, store):
        self.store = store
        with store.transaction() as db:
            db.create_function('openhmi_image_casefold', 1, str.casefold, deterministic=True)
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

    def list(self, before, limit, search=''):
        conditions, parameters = [], []
        if before is not None:
            conditions.append('rowid < ?')
            parameters.append(before)
        term = search.strip().casefold()
        if term:
            conditions.append('(instr(openhmi_image_casefold(name), ?) > 0 OR instr(id, ?) = 1)')
            parameters.extend((term, term))
        where = ' WHERE ' + ' AND '.join(conditions) if conditions else ''
        with self.store._lock:
            rows = self.store._db.execute('SELECT rowid, id, name FROM canvas_image' + where
                                          + ' ORDER BY rowid DESC LIMIT ?', (*parameters, limit + 1)).fetchall()
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


# Compatibility export for existing service imports.
from .canvas_routes import add_canvas_routes
