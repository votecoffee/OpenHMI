from contextlib import closing
import hashlib
from io import BytesIO
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from openhmi.projects import ProjectStore
from openhmi.workspace import ProjectWorkspace


class CanvasBackupTests(unittest.TestCase):
    def test_canvas_background_survives_backup_and_image_references_are_checked(self):
        directory = self.enterContext(TemporaryDirectory())
        path = Path(directory) / 'Canvas.openhmi.sqlite3'
        legacy = BytesIO()
        Image.new('RGB', (20, 20), '#f0f0f0').save(legacy, format='WEBP')
        legacy_id = hashlib.sha256(legacy.getvalue()).hexdigest()
        ProjectStore(path).close()
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE canvas_image (id TEXT PRIMARY KEY, media_type TEXT NOT NULL, data BLOB NOT NULL)')
            db.execute('INSERT INTO canvas_image VALUES (?, ?, ?)', (legacy_id, 'image/webp', legacy.getvalue()))
        workspace = ProjectWorkspace(path)
        self.addCleanup(workspace.current.state.store.close)
        client = TestClient(workspace.current)
        state = client.get('/api/project').json()
        self.assertEqual(client.get('/api/canvas-images').json()['items'], [{'id': legacy_id, 'name': ''}])
        project = state['draft']
        background = BytesIO()
        Image.new('RGB', (40, 30), '#789abc').save(background, format='PNG')
        invalid = client.post('/api/canvas-images', content=b'<svg/>')
        self.assertEqual(invalid.status_code, 422)
        image = client.post('/api/canvas-images', content=background.getvalue(), params={'name': r'C:\fixture\Background.png'})
        self.assertEqual(image.status_code, 200, image.text)
        identifier = image.json()['id']
        off = BytesIO()
        Image.new('RGB', (40, 30), '#123456').save(off, format='PNG')
        off_image = client.post('/api/canvas-images', content=off.getvalue(), params={'name': 'Straße.png'})
        self.assertEqual(off_image.status_code, 200, off_image.text)
        off_id = off_image.json()['id']
        duplicate = client.post('/api/canvas-images', content=off.getvalue(), params={'name': 'Copy.png'})
        self.assertEqual(duplicate.json()['id'], off_id)
        newest = client.get('/api/canvas-images', params={'limit': 1}).json()
        self.assertEqual(newest['items'], [{'id': off_id, 'name': 'Straße.png'}])
        older = client.get('/api/canvas-images', params={'before': newest['next_before']}).json()
        self.assertEqual(older['items'], [{'id': identifier, 'name': 'Background.png'}, {'id': legacy_id, 'name': ''}])
        self.assertIsNone(older['next_before'])
        match = client.get('/api/canvas-images', params={'search': ' STRASSE '}).json()
        self.assertEqual(match['items'], [{'id': off_id, 'name': 'Straße.png'}])
        by_id = client.get('/api/canvas-images', params={'search': legacy_id[:8].upper()}).json()
        self.assertEqual(by_id['items'], [{'id': legacy_id, 'name': ''}])
        filtered = client.get('/api/canvas-images', params={'search': 'PNG', 'limit': 1}).json()
        self.assertEqual(filtered['items'], newest['items'])
        next_page = client.get('/api/canvas-images', params={'search': 'PNG', 'before': filtered['next_before']}).json()
        self.assertEqual(next_page['items'], [{'id': identifier, 'name': 'Background.png'}])
        self.assertIsNone(next_page['next_before'])
        state_image = {'id': 'valve', 'kind': 'state_image', 'label': 'Valve', 'tag': 'MotorRunning',
                       'on_image': identifier, 'off_image': 'f' * 64}
        positions = {'id': 'positions', 'kind': 'multi_state_image', 'label': 'Positions', 'tag': 'AlarmWord',
                     'states': [{'value': 0, 'label': 'Closed', 'image': off_id},
                                {'value': 1, 'label': 'Open', 'image': 'e' * 64}]}
        travel = {'id': 'travel', 'kind': 'position_image', 'label': 'Travel', 'tag': 'TankLevel', 'image': 'd' * 64}
        rotation = {'id': 'rotation', 'kind': 'rotation_image', 'label': 'Rotation', 'tag': 'TankLevel', 'image': 'c' * 64}
        static_image = {'id': 'drawing', 'kind': 'image', 'label': 'Drawing', 'image': 'b' * 64}
        project['faceplates'] = [{'id': 'equipment', 'name': 'Equipment', 'members': {}, 'controls': [static_image]}]
        project['controls'] += [state_image, positions, travel, rotation]
        project['layout'] = {'background': '0' * 64, 'boxes': {
            control['id']: {'x': index * 100, 'y': 0, 'width': 80, 'height': 48}
            for index, control in enumerate(project['controls'])
        }}
        request = {'project': project, 'expected_revision': state['draft_revision']}
        self.assertEqual(client.put('/api/project/draft', json=request).status_code, 422)
        project['layout']['background'] = identifier
        project['layout']['decorations'] = {'machine': {'kind': 'image', 'label': 'Machine', 'image': 'f' * 64,
                                                       'locked': True, 'x': 0, 'y': 0, 'width': 640, 'height': 400}}
        self.assertEqual(client.put('/api/project/draft', json=request).status_code, 422)
        project['layout']['decorations']['machine']['image'] = identifier
        self.assertEqual(client.put('/api/project/draft', json=request).status_code, 422)
        state_image['off_image'] = off_id
        self.assertEqual(client.put('/api/project/draft', json=request).status_code, 422)
        positions['states'][1]['image'] = identifier
        self.assertEqual(client.put('/api/project/draft', json=request).status_code, 422)
        travel['image'] = off_id
        self.assertEqual(client.put('/api/project/draft', json=request).status_code, 422)
        rotation['image'] = identifier
        self.assertEqual(client.put('/api/project/draft', json=request).status_code, 422)
        static_image['image'] = off_id
        saved = client.put('/api/project/draft', json=request)
        self.assertEqual(saved.status_code, 200, saved.text)
        applied = client.post('/api/project/apply', json={'expected_revision': saved.json()['draft_revision']})
        self.assertEqual(applied.status_code, 200, applied.text)
        workspace.import_backup('Restored', workspace.export())
        restored = workspace._app(Path(directory) / 'Restored.openhmi.sqlite3')
        try:
            restored_client = TestClient(restored)
            current = restored_client.get('/api/project').json()['active']
            self.assertEqual(restored_client.get('/api/canvas-images').json(), client.get('/api/canvas-images').json())
            self.assertEqual(current['layout']['background'], identifier)
            self.assertTrue(current['layout']['decorations']['machine']['locked'])
            self.assertEqual(current['layout']['decorations']['machine']['image'], identifier)
            asset = '/api/canvas-images/' + identifier
            self.assertEqual(restored_client.get(asset).content, client.get(asset).content)
            restored_image = next(control for control in current['controls'] if control['id'] == 'valve')
            self.assertEqual((restored_image['on_image'], restored_image['off_image']), (identifier, off_id))
            restored_positions = next(control for control in current['controls'] if control['id'] == 'positions')
            self.assertEqual(restored_positions['states'], positions['states'])
            restored_travel = next(control for control in current['controls'] if control['id'] == 'travel')
            self.assertEqual(restored_travel['image'], off_id)
            restored_rotation = next(control for control in current['controls'] if control['id'] == 'rotation')
            self.assertEqual(restored_rotation['image'], identifier)
            self.assertEqual(current['faceplates'][0]['controls'][0]['image'], off_id)
            off_asset = '/api/canvas-images/' + off_id
            self.assertEqual(restored_client.get(off_asset).content, client.get(off_asset).content)
        finally:
            restored.state.store.close()
