"""Synthetic filesystem fault injection for staged, no-replace project publication."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from openhmi.workspace import ProjectWorkspace
from openhmi import workspace_publication as publication


class WorkspacePublicationTests(unittest.TestCase):
    def fixture(self):
        directory = self.enterContext(TemporaryDirectory())
        workspace = ProjectWorkspace(Path(directory) / 'Original.openhmi.sqlite3', hold_connections=True)
        self.addCleanup(workspace.current.state.store.close)
        self.addCleanup(workspace.current.state.driver.close)
        workspace.current.state.driver.factory = Mock(side_effect=AssertionError('Offline test cannot connect to a PLC'))
        handler = Path(directory) / 'review-only.py'
        handler.write_bytes(b'raise AssertionError("Imported Python must not execute automatically")\n')
        workspace.handlers = handler
        workspace.recipe_users = {'users': []}
        backup = workspace.export()
        client = TestClient(workspace)  # No lifespan/background acquisition.
        self.addCleanup(client.close)
        return workspace, client, backup

    def import_project(self, client, backup, name='Imported'):
        return client.post('/api/workspace/import?name=' + name, content=backup)

    def assert_unpublished(self, workspace, name='Imported'):
        target = workspace.target(name)
        self.assertFalse(target.exists())
        self.assertFalse(any(path.exists() for path in publication.companion_paths(target)))
        self.assertNotIn(target.name, [item['file'] for item in workspace.listing()['projects']])
        workspace.current.state.driver.factory.assert_not_called()

    def test_failed_create_initialization_never_exposes_empty_project_and_can_retry(self):
        workspace, client, _ = self.fixture()
        target = workspace.target('Created')
        def fail(path, **kwargs):
            self.assertNotEqual(path, target)
            self.assertEqual(path.parent.parent, workspace.root)
            self.assertFalse(target.exists())
            raise sqlite3.OperationalError('Private offline storage failure marker')
        with patch('openhmi.workspace.ProjectStore', side_effect=fail), self.assertLogs(level='ERROR'):
            response = client.post('/api/workspace/create', json={'name': 'Created', 'title': 'Created machine'})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('Private offline', response.text)
        self.assertEqual(response.headers['X-OpenHMI-Project'], workspace.current.state.project_instance)
        self.assert_unpublished(workspace, 'Created')
        response = client.post('/api/workspace/create', json={'name': 'Created', 'title': 'Created machine'})
        self.assertEqual(response.status_code, 200, response.text)
        with closing(sqlite3.connect(target)) as db:
            state = json.loads(db.execute('SELECT state FROM project WHERE id=1').fetchone()[0])
        self.assertEqual(state['active']['title'], 'Created machine')

    def test_import_publication_failure_rolls_back_only_owned_files_and_retry_preserves_hold(self):
        workspace, client, backup = self.fixture()
        publish = publication._publish_file
        attempts = 0
        def fail_second(source, target):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise OSError('Offline second publication failure')
            publish(source, target)
        with patch.object(publication, '_publish_file', side_effect=fail_second), self.assertLogs(level='ERROR'):
            response = self.import_project(client, backup)
        self.assertEqual(response.status_code, 503)
        self.assert_unpublished(workspace)
        response = self.import_project(client, backup)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['plc_hold'])
        self.assertTrue(response.json()['handlers_saved_for_review'])
        target = workspace.target('Imported')
        self.assertTrue(target.with_suffix('.hold').exists())
        self.assertEqual(target.with_suffix('.handlers.py').read_bytes(), workspace.handlers.read_bytes())
        self.assertEqual(json.loads(target.with_suffix('.recipe-users.json').read_bytes()), {'users': []})
        with closing(sqlite3.connect(target)) as db:
            identity = db.execute('SELECT project_id FROM project_storage WHERE id=1').fetchone()[0]
        self.assertNotEqual(identity, workspace.current.state.store.snapshot()['project_id'])

    def test_incomplete_staged_companion_never_publishes_any_final_files(self):
        workspace, client, backup = self.fixture()
        write = Path.write_bytes
        def short_write(path, content):
            if path.name == 'Imported.openhmi.handlers.py':
                return write(path, b'short')
            return write(path, content)
        with patch.object(Path, 'write_bytes', new=short_write), \
             patch.object(publication, '_publish_file') as publish, self.assertLogs(level='ERROR'):
            response = self.import_project(client, backup)
        self.assertEqual(response.status_code, 503)
        publish.assert_not_called()
        self.assert_unpublished(workspace)

    def test_orphan_support_and_sqlite_recovery_files_are_preserved_and_block_reuse(self):
        workspace, client, backup = self.fixture()
        for index in range(6):
            name = 'Guard' + str(index)
            target = workspace.target(name)
            artifact = publication.companion_paths(target)[index]
            artifact.write_bytes(b'Uncertain existing recovery record')
            with self.subTest(artifact=artifact.name):
                response = client.post('/api/workspace/create', json={'name': name, 'title': 'Should not replace'})
                self.assertEqual(response.status_code, 409)
                self.assertEqual(self.import_project(client, backup, name).status_code, 409)
                self.assertFalse(target.exists())
                self.assertEqual(artifact.read_bytes(), b'Uncertain existing recovery record')
        workspace.current.state.driver.factory.assert_not_called()

    def test_destination_race_preserves_existing_database_and_companions_for_review(self):
        workspace, client, backup = self.fixture()
        publish = publication._publish_file
        target = workspace.target('Imported')
        def collide(source, destination):
            if destination == target:
                destination.write_bytes(b'Existing external project record')
            publish(source, destination)
        with patch.object(publication, '_publish_file', side_effect=collide), self.assertLogs(level='WARNING'):
            response = self.import_project(client, backup)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(target.read_bytes(), b'Existing external project record')
        self.assertTrue(target.with_suffix('.hold').exists())
        self.assertIn('retained', response.json()['detail'])

    def test_changed_artifact_is_retained_and_blocks_unsafe_retry(self):
        workspace, client, backup = self.fixture()
        publish = publication._publish_file
        target = workspace.target('Imported')
        hold = target.with_suffix('.hold')
        def fail(source, destination):
            if destination == target:
                hold.write_bytes(b'Changed externally; preserve this record')
                raise OSError('Offline database publication failure')
            publish(source, destination)
        with patch.object(publication, '_publish_file', side_effect=fail), self.assertLogs(level='ERROR'):
            response = self.import_project(client, backup)
        self.assertEqual(response.status_code, 503)
        self.assertIn('retained', response.json()['detail'])
        self.assertFalse(target.exists())
        self.assertEqual(hold.read_bytes(), b'Changed externally; preserve this record')
        self.assertFalse(target.with_suffix('.handlers.py').exists())
        self.assertFalse(target.with_suffix('.recipe-users.json').exists())
        self.assertEqual(self.import_project(client, backup).status_code, 409)
        self.assertEqual(client.post('/api/workspace/create', json={'name': 'Imported', 'title': 'Do not reuse'}).status_code, 409)
        self.assertEqual(hold.read_bytes(), b'Changed externally; preserve this record')

    def test_failed_rollback_retains_hold_and_returns_review_guidance(self):
        workspace, client, backup = self.fixture()
        publish = publication._publish_file
        target = workspace.target('Imported')
        hold = target.with_suffix('.hold')
        unlink = Path.unlink
        def fail_publish(source, destination):
            if destination == target:
                raise OSError('Offline final publication failure')
            publish(source, destination)
        def fail_rollback(path, *args, **kwargs):
            if path == hold:
                raise PermissionError('Offline rollback denied')
            return unlink(path, *args, **kwargs)
        with patch.object(publication, '_publish_file', side_effect=fail_publish), \
             patch.object(Path, 'unlink', new=fail_rollback), self.assertLogs(level='ERROR') as logs:
            response = self.import_project(client, backup)
        self.assertEqual(response.status_code, 503)
        self.assertIn('retained', response.json()['detail'])
        self.assertFalse(target.exists())
        self.assertTrue(hold.exists())
        self.assertTrue(any('Could not roll back project publication artifact' in line for line in logs.output))
        self.assertEqual(self.import_project(client, backup).status_code, 409)

    def test_uncertain_completed_publication_retains_valid_database_and_required_hold(self):
        workspace, client, backup = self.fixture()
        publish = publication._publish_file
        target = workspace.target('Imported')
        def uncertain(source, destination):
            publish(source, destination)
            if destination == target:
                raise OSError('Offline error after database publication')
        with patch.object(publication, '_publish_file', side_effect=uncertain), self.assertLogs(level='ERROR'):
            response = self.import_project(client, backup)
        self.assertEqual(response.status_code, 503)
        self.assertTrue(target.with_suffix('.hold').exists())
        self.assertTrue(target.with_suffix('.handlers.py').exists())
        self.assertTrue(target.with_suffix('.recipe-users.json').exists())
        with closing(sqlite3.connect(target)) as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertIn(target.name, [item['file'] for item in workspace.listing()['projects']])
        before = target.read_bytes()
        self.assertEqual(self.import_project(client, backup).status_code, 409)
        self.assertEqual(target.read_bytes(), before)
        workspace.current.state.driver.factory.assert_not_called()
