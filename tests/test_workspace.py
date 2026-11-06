import asyncio
from io import BytesIO
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from openhmi.workspace import ProjectWorkspace


class WorkspaceTests(unittest.TestCase):
    def test_complete_history_download_does_not_wait_for_workspace_lock(self):
        async def download(workspace):
            async with AsyncClient(transport=ASGITransport(app=workspace), base_url='http://test') as client:
                async with workspace.lock:
                    response = await asyncio.wait_for(client.get('/api/history/full.csv?tags=TankLevel'), timeout=5)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('tag,timestamp,value,quality,source_timestamp', response.text)

        with TemporaryDirectory() as directory:
            workspace = ProjectWorkspace(Path(directory) / 'Original.openhmi.sqlite3')
            try:
                asyncio.run(download(workspace))
            finally:
                workspace.current.state.store.close()

    def test_complete_backup_create_open_import_and_connection_hold(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'Original.openhmi.sqlite3'
            handler = Path(directory) / 'custom.py'
            handler.write_text('def register(app):\n    app.register_action("test", "Test", lambda app: None)\n', encoding='utf-8')
            workspace = ProjectWorkspace(path, handler)
            with TestClient(workspace) as client:
                app = workspace.current
                operation = client.post('/api/controls/toggle/activate', json={})
                self.assertEqual(operation.status_code, 200, operation.text)
                operation_id = operation.headers['X-OpenHMI-Operation-ID']
                from tests.test_commands import command_project, install
                install(client, command_project(client.get('/api/project').json()['draft']))
                dispatched = client.post('/api/controls/cycle/activate', json={})
                self.assertEqual(dispatched.status_code, 200, dispatched.text)
                command_id = dispatched.json()['transaction']['id']
                with app.state.store.transaction() as db:
                    db.execute("INSERT INTO recipe_image VALUES('fixture',?,1,1)", (b'synthetic-image',))
                    db.execute("INSERT INTO tag_history(tag,timestamp,value,quality) VALUES('TankLevel',?,'42','good')", (time.time(),))
                backup = client.get('/api/workspace/backup')
                self.assertEqual(backup.status_code, 200, backup.text if backup.status_code != 200 else '')
                archive = zipfile.ZipFile(BytesIO(backup.content))
                self.assertIn('handlers.py', archive.namelist())
                created = client.post('/api/workspace/create', json={'name': 'NewProject', 'title': 'New machine'})
                self.assertEqual(created.status_code, 200, created.text)
                self.assertEqual(client.post('/api/workspace/create', json={'name': 'NewProject', 'title': 'Overwrite'}).status_code, 409)
                imported = client.post('/api/workspace/import?name=Restored', content=backup.content)
                self.assertEqual(imported.status_code, 200, imported.text)
                self.assertTrue(imported.json()['handlers_saved_for_review'])
                self.assertEqual(client.post('/api/workspace/open', json={'file': 'Restored.openhmi.sqlite3'}).status_code, 200)
                self.assertTrue(client.get('/api/tags').json()['plc_hold'])
                self.assertNotIn('test', [action['name'] for action in client.get('/api/catalog').json()['actions']])
                self.assertEqual(workspace.current.state.recipes.image('fixture'), b'synthetic-image')
                self.assertEqual(workspace.current.state.activity.query(search=operation_id)['items'][0]['status'], 'succeeded')
                restored_command = workspace.current.state.commands.get(command_id)
                self.assertEqual(restored_command['state'], 'uncertain')
                self.assertEqual(restored_command['sequence'], 1)
                self.assertEqual(workspace.current.state.driver._tags['CycleCommand']['RequestSequence'], 0)
                self.assertEqual(len(workspace.current.state.historian.query(['TankLevel'], time.time() - 60, time.time() + 60)['samples']), 1)
                state = client.get('/api/project').json()
                self.assertEqual(client.post('/api/project/apply', json={'expected_revision': state['draft_revision']}).status_code, 200)
                self.assertFalse(client.get('/api/tags').json()['plc_hold'])
                self.assertFalse((Path(directory) / 'Restored.openhmi.hold').exists())
                self.assertEqual(client.post('/api/workspace/open', json={'file': created.json()['file']}).status_code, 200)
                self.assertEqual(client.get('/api/project').json()['active']['title'], 'New machine')
                self.assertNotEqual(client.get('/api/project/active').json()['project_instance'], state['project_instance'])
                self.assertEqual(client.post('/api/project/apply', json={'expected_revision': 1}, headers={'X-OpenHMI-Project': state['project_instance']}).status_code, 409)
                self.assertTrue(path.exists())

    def test_recovery_start_holds_applied_plc_routes_and_new_project_opens(self):
        from openhmi.projects import Project, ProjectStore
        from tests.test_logix_history import FakePLC, logix_project

        with TemporaryDirectory() as directory:
            path = Path(directory) / 'Original.openhmi.sqlite3'
            ProjectStore(path, initial_project=Project.model_validate(logix_project())).close()
            workspace = ProjectWorkspace(path, hold_connections=True)
            with TestClient(workspace) as client:
                driver = workspace.current.state.driver
                self.assertFalse(driver.connections)
                held = client.get('/api/tags').json()
                self.assertTrue(held['plc_hold'])
                self.assertEqual(held['samples']['LevelA']['quality_reason'], 'held')
                self.assertNotIn('LevelA', held['values'])

                driver.factory = FakePLC
                state = client.get('/api/project').json()
                applied = client.post('/api/project/apply', json={'expected_revision': state['draft_revision']})
                self.assertEqual(applied.status_code, 200, applied.text)
                self.assertFalse(client.get('/api/tags').json()['plc_hold'])
                self.assertIn('plc', driver.connections)

                created = client.post('/api/workspace/create', json={'name': 'Other', 'title': 'Other project'})
                self.assertEqual(created.status_code, 200, created.text)
                opened = client.post('/api/workspace/open', json={'file': created.json()['file']})
                self.assertEqual(opened.status_code, 200, opened.text)
                self.assertTrue(client.get('/api/tags').json()['plc_hold'])
                reopened = client.post('/api/workspace/open', json={'file': path.name})
                self.assertEqual(reopened.status_code, 200, reopened.text)
                self.assertFalse(workspace.current.state.driver.connections)
                self.assertTrue(client.get('/api/tags').json()['plc_hold'])

    def test_backup_corruption_paths_and_security_are_rejected(self):
        with TemporaryDirectory() as directory:
            workspace = ProjectWorkspace(Path(directory) / 'Original.openhmi.sqlite3')
            from tests.test_security import bootstrap, PASSWORD
            bootstrap(workspace.current)
            with TestClient(workspace) as client:
                self.assertEqual(client.get('/api/workspace/backup').status_code, 401)
                client.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD})
                backup = client.get('/api/workspace/backup').content
                self.assertEqual(client.post('/api/workspace/create', json={'name': '../escape', 'title': 'bad'}).status_code, 422)
                self.assertEqual(client.post('/api/workspace/open', json={'file': '../escape.sqlite3'}).status_code, 404)
                self.assertEqual(client.post('/api/workspace/import?name=Corrupt', content=b'bad').status_code, 422)
                source = zipfile.ZipFile(BytesIO(backup))
                changed = BytesIO()
                with zipfile.ZipFile(changed, 'w') as archive:
                    for name in source.namelist():
                        archive.writestr(name, b'corrupted' if name == 'project.sqlite3' else source.read(name))
                self.assertEqual(client.post('/api/workspace/import?name=Corrupt', content=changed.getvalue()).status_code, 422)
                self.assertFalse((Path(directory) / 'Corrupt.openhmi.sqlite3').exists())
                self.assertEqual(client.post('/api/workspace/create', json={'name': 'Secured', 'title': 'Secured new project'}).status_code, 200)
                client.post('/api/workspace/open', json={'file': 'Secured.openhmi.sqlite3'})
                self.assertEqual(client.post('/api/project/apply', json={'expected_revision': 1}).status_code, 401)
                self.assertEqual(client.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD}).status_code, 200)
                self.assertEqual(client.get('/api/workspace').status_code, 200)
