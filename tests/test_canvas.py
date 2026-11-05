from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi.testclient import TestClient
from PIL import Image

from openhmi.workspace import ProjectWorkspace


class CanvasBackupTests(unittest.TestCase):
    def test_canvas_background_survives_backup_and_image_references_are_checked(self):
        directory = self.enterContext(TemporaryDirectory())
        workspace = ProjectWorkspace(Path(directory) / 'Canvas.openhmi.sqlite3')
        self.addCleanup(workspace.current.state.store.close)
        client = TestClient(workspace.current)
        state = client.get('/api/project').json()
        project = state['draft']
        background = BytesIO()
        Image.new('RGB', (40, 30), '#789abc').save(background, format='PNG')
        invalid = client.post('/api/canvas-images', content=b'<svg/>')
        self.assertEqual(invalid.status_code, 422)
        image = client.post('/api/canvas-images', content=background.getvalue())
        self.assertEqual(image.status_code, 200, image.text)
        identifier = image.json()['id']
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
        saved = client.put('/api/project/draft', json=request)
        self.assertEqual(saved.status_code, 200, saved.text)
        applied = client.post('/api/project/apply', json={'expected_revision': saved.json()['draft_revision']})
        self.assertEqual(applied.status_code, 200, applied.text)
        workspace.import_backup('Restored', workspace.export())
        restored = workspace._app(Path(directory) / 'Restored.openhmi.sqlite3')
        try:
            restored_client = TestClient(restored)
            current = restored_client.get('/api/project').json()['active']
            self.assertEqual(current['layout']['background'], identifier)
            self.assertTrue(current['layout']['decorations']['machine']['locked'])
            self.assertEqual(current['layout']['decorations']['machine']['image'], identifier)
            asset = '/api/canvas-images/' + identifier
            self.assertEqual(restored_client.get(asset).content, client.get(asset).content)
        finally:
            restored.state.store.close()
