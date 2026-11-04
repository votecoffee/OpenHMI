"""Project revision, migration and merge checks; configuration recovery never writes PLC tags."""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from openhmi.projects import ProjectStore, Project, default_project, RevisionRequest, SaveRequest
from openhmi.project_diff import merge_project, differences
from openhmi.server import create_app
from tests.test_commands import command_project, install
from tests.test_security import bootstrap, PASSWORD
from tests.test_logix_history import logix_project, FakePLC


class ProjectHistoryTests(unittest.TestCase):
    def setup_app(self, path=None):
        app = create_app(path)
        self.addCleanup(app.state.store.close)
        self.addCleanup(app.state.driver.close)
        client = TestClient(app)
        self.addCleanup(client.close)
        return app, client

    def apply(self, client, title, reason='Test apply'):
        state = client.get('/api/project').json()
        project = state['draft']; project['title'] = title
        response = client.put('/api/project/draft', json={'expected_revision': state['draft_revision'], 'project': project})
        response.raise_for_status()
        result = client.post('/api/project/apply', json={'expected_revision': response.json()['draft_revision'], 'reason': reason})
        result.raise_for_status()
        return result.json()

    def test_applied_history_staging_provenance_and_restart(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'project.sqlite3'
            app, client = self.setup_app(path)
            initial = client.get('/api/project').json()
            self.apply(client, 'Second', 'Reviewed change')
            history = client.get('/api/project/revisions').json()
            self.assertEqual([item['revision'] for item in history['items']], [2, 1])
            self.assertEqual(history['items'][0]['actor'], 'unsecured-simulation')
            self.assertEqual(history['items'][0]['reason'], 'Reviewed change')
            state = client.get('/api/project').json()
            comparison = client.get('/api/project/revisions/1/compare').json()
            self.assertIn('/title', [item['path'] for item in comparison['changes']])
            staged = client.post('/api/project/revisions/1/stage', json={'expected_revision': state['draft_revision'], 'reason': 'Restore first screen'})
            staged.raise_for_status()
            self.assertEqual(staged.json()['active']['title'], 'Second')
            self.assertEqual(staged.json()['draft']['title'], initial['draft']['title'])
            self.assertEqual(app.state.store.recovery(staged.json()['preserved_recovery_id'])['local']['title'], 'Second')
            result = client.post('/api/project/apply', json={'expected_revision': staged.json()['draft_revision']})
            result.raise_for_status()
            self.assertEqual(result.json()['active_revision'], 3)
            revision = client.get('/api/project/revisions/3').json()
            self.assertEqual((revision['source_revision'], revision['reason']), (1, 'Restore first screen'))
            app.state.store.close()
            reopened = ProjectStore(path)
            try:
                self.assertEqual(len(reopened.revisions()['items']), 3)
                self.assertEqual(reopened.snapshot()['project_id'], initial['project_id'])
                reopened.verify_history()
            finally:
                reopened.close()

    def test_screen_restore_keeps_driver_connection_live_values_and_pending_commands(self):
        app, client = self.setup_app()
        app.state.driver.factory = FakePLC
        project = logix_project()
        project['tags'].append({'name': 'LocalKeep', 'type': 'number', 'initial': 9.0, 'writable': True})
        install(client, project)
        app.state.driver.poll()
        connection = app.state.driver.connections['plc']
        app.state.driver.write('TankLevel', [19.0])
        app.state.driver.write('LocalKeep', [33.0])
        state = client.get('/api/project').json()
        stage = client.post('/api/project/revisions/1/stage', json={'expected_revision': state['draft_revision'], 'reason': 'Screen only'})
        stage.raise_for_status()
        self.assertEqual(stage.json()['draft']['connections'], state['draft']['connections'])
        with patch.object(app.state.driver, 'write', wraps=app.state.driver.write) as writer:
            client.post('/api/project/apply', json={'expected_revision': stage.json()['draft_revision']}).raise_for_status()
            writer.assert_not_called()
        self.assertIs(app.state.driver.connections['plc'], connection)
        self.assertEqual(app.state.driver.read('TankLevel')[0], 19.0)
        self.assertEqual(app.state.driver.read('LocalKeep')[0], 33.0)
        app2, second = self.setup_app()
        install(second, command_project(second.get('/api/project').json()['draft']))
        second.post('/api/controls/cycle/activate', json={}).raise_for_status()
        state = second.get('/api/project').json()
        staged = second.post('/api/project/revisions/1/stage', json={'expected_revision': state['draft_revision'], 'reason': 'Review old full project', 'scope': 'project'})
        staged.raise_for_status()
        with patch.object(app2.state.driver, 'write_command_request') as writer:
            self.assertEqual(second.post('/api/project/apply', json={'expected_revision': staged.json()['draft_revision']}).status_code, 409)
            writer.assert_not_called()
        self.assertEqual(app2.state.commands.recent()['items'][0]['state'], 'requested')

    def test_legacy_baseline_migration_preserves_original_counters_and_data(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy.sqlite3'
            project = default_project().model_dump(); project.pop('recipe_transfers'); project.pop('commands')
            state = {'draft_revision': 9, 'active_revision': 7, 'draft': {**project, 'title': 'Unapplied draft'}, 'active': project}
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE project(id INTEGER PRIMARY KEY,state TEXT)')
                db.execute('INSERT INTO project VALUES(1,?)', (json.dumps(state),))
            before = path.read_bytes()
            store = ProjectStore(path)
            try:
                self.assertEqual(store.snapshot()['draft_revision'], 9)
                self.assertEqual(store.snapshot()['draft']['title'], 'Unapplied draft')
                items = store.revisions()['items']
                self.assertEqual(len(items), 1)
                self.assertEqual((items[0]['revision'], items[0]['actor'], items[0]['baseline']), (7, 'unknown', True))
                self.assertEqual(store._read(), state)
            finally: store.close()
            reopened = ProjectStore(path)
            self.assertEqual(len(reopened.revisions()['items']), 1); reopened.close()
            self.assertNotEqual(path.read_bytes(), before)  # Additive history, no invented earlier revisions.

    def test_future_or_damaged_project_is_rejected_without_file_changes(self):
        for damage in ('storage', 'schema', 'active'):
            with self.subTest(damage=damage), TemporaryDirectory() as directory:
                path = Path(directory) / 'future.sqlite3'
                store = ProjectStore(path); store.close()
                with closing(sqlite3.connect(path)) as db, db:
                    if damage == 'storage': db.execute('UPDATE project_storage SET version=999')
                    else:
                        state = json.loads(db.execute('SELECT state FROM project').fetchone()[0])
                        if damage == 'schema': state['active']['schema_version'] = 999
                        else: state['active']['title'] = 'Unrecorded mutation'
                        db.execute('UPDATE project SET state=?', (json.dumps(state),))
                before = hashlib.sha256(path.read_bytes()).hexdigest()
                with self.assertRaises(ValueError): ProjectStore(path)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_history_insert_and_active_apply_are_one_transaction(self):
        store = ProjectStore(); self.addCleanup(store.close)
        project = default_project(); project.title = 'SQL failure candidate'
        saved = store.save(SaveRequest(expected_revision=1, project=project))
        with store.transaction() as db:
            db.execute("CREATE TRIGGER fail_history BEFORE INSERT ON project_revision BEGIN SELECT RAISE(ABORT,'synthetic outage'); END")
        with self.assertRaises(sqlite3.IntegrityError): store.apply(RevisionRequest(expected_revision=saved['draft_revision']))
        self.assertEqual(store.snapshot()['active_revision'], 1)
        self.assertEqual(store.snapshot()['draft']['title'], 'SQL failure candidate')
        self.assertEqual(len(store.revisions()['items']), 1)

    def test_identity_merge_independent_changes_deletions_order_and_boolean_types(self):
        base = default_project().model_dump(); local, current = deepcopy(base), deepcopy(base)
        local['controls'][0]['label'] = 'Local level'; current['controls'][1]['label'] = 'Current motor'
        combined = merge_project(base, local, current)
        self.assertTrue(combined['complete'])
        self.assertEqual(combined['project']['controls'][0]['label'], 'Local level')
        self.assertEqual(combined['project']['controls'][1]['label'], 'Current motor')
        current['controls'][0]['label'] = 'Current level'
        conflict = merge_project(base, local, current)
        self.assertFalse(conflict['complete'])
        self.assertEqual(conflict['conflicts'][0]['path'], '/controls/@level/label')
        self.assertEqual(merge_project(base, local, current, {'/controls/@level/label': 'local'})['project']['controls'][0]['label'], 'Local level')
        local['controls'] = local['controls'][1:]
        deleted = merge_project(base, local, current)
        self.assertIn('/controls/@level', [item['path'] for item in deleted['conflicts']])
        a, b = deepcopy(base), deepcopy(base)
        a['controls'].append({'id': 'newA', 'kind': 'recipe', 'label': 'A'})
        b['controls'].append({'id': 'newB', 'kind': 'recipe', 'label': 'B'})
        result = merge_project(base, a, b, {'/controls/@order': 'local'})
        self.assertEqual({item['id'] for item in result['project']['controls']}, {item['id'] for item in base['controls']} | {'newA', 'newB'})
        self.assertTrue(differences({'value': True}, {'value': 1}))
        with self.assertRaises(ValueError): merge_project(base, local, current, {'/wrong': 'local'})
        data = {'tags': [{'name': 'A', 'initial': {'controls': [{'id': 'one', 'value': 1}, {'id': 'two', 'value': 2}]}}]}
        local, current = deepcopy(data), deepcopy(data)
        local['tags'][0]['initial']['controls'][0]['value'] = 3
        current['tags'][0]['initial']['controls'][1]['value'] = 4
        self.assertEqual(merge_project(data, local, current)['conflicts'][0]['path'], '/tags/@A/initial/controls')

    def test_reviewed_merge_preserves_both_candidates_and_requires_current_counter(self):
        app, client = self.setup_app()
        state = client.get('/api/project').json(); base = state['draft']; local = deepcopy(base)
        local['controls'][0]['label'] = 'My level'
        current = deepcopy(base); current['controls'][0]['label'] = 'Their level'
        current['title'] = 'Concurrent project'
        client.put('/api/project/draft', json={'expected_revision': 1, 'project': current}).raise_for_status()
        preview = client.post('/api/project/merge-preview', json={'base': base, 'local': local}).json()
        self.assertFalse(preview['complete'])
        body = {'base': base, 'local': local, 'base_revision': state['draft_revision'], 'expected_revision': preview['draft_revision'], 'reason': 'Reviewed conflict'}
        self.assertEqual(client.post('/api/project/merge', json=body).status_code, 409)
        body['choices'] = {'/controls/@level/label': 'local'}
        merged = client.post('/api/project/merge', json=body); merged.raise_for_status()
        self.assertEqual(merged.json()['draft']['title'], 'Concurrent project')
        self.assertEqual(merged.json()['draft']['controls'][0]['label'], 'My level')
        self.assertEqual(merged.json()['active']['controls'][0]['label'], base['controls'][0]['label'])
        self.assertEqual(len(app.state.store.recoveries()['items']), 2)
        self.assertEqual(client.post('/api/project/merge', json=body).status_code, 409)

    def test_authenticated_history_recovery_and_staging_permissions(self):
        app, client = self.setup_app(); bootstrap(app)
        state = app.state.store.snapshot(); candidate = {'base': state['draft'], 'local': state['draft'], 'base_revision': 1, 'reason': 'Retain candidate'}
        for url in ('/api/project/revisions', '/api/project/revisions/1', '/api/project/recoveries'):
            self.assertEqual(client.get(url).status_code, 401)
        self.assertEqual(client.post('/api/project/recoveries', json=candidate).status_code, 401)
        client.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD}).raise_for_status()
        copy = client.post('/api/project/recoveries', json=candidate); copy.raise_for_status()
        self.assertEqual(copy.json()['actor'], 'admin')
        self.apply(client, 'Authenticated change', 'Signed-in apply')
        history = client.get('/api/project/revisions/2').json()
        self.assertEqual((history['actor'], history['provider']), ('admin', 'local'))
        self.assertEqual(client.get('/api/project/revisions/9999999999999999999999').status_code, 422)
        self.assertEqual(client.get('/api/project/recoveries/not-a-uuid').status_code, 422)
        self.assertEqual(client.get('/api/project/revisions/999').status_code, 404)

    def test_staging_cas_and_pagination(self):
        app, client = self.setup_app()
        self.apply(client, 'Second'); self.apply(client, 'Third')
        first = client.get('/api/project/revisions?limit=1').json()
        self.assertEqual(first['items'][0]['revision'], 3)
        self.assertEqual(client.get('/api/project/revisions?limit=1&before_revision=3').json()['items'][0]['revision'], 2)
        state = client.get('/api/project').json()
        body = {'expected_revision': state['draft_revision'], 'reason': 'Concurrent restore'}
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: client.post('/api/project/revisions/1/stage', json=body), range(2)))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        copies = client.get('/api/project/recoveries?limit=1').json()
        self.assertEqual(len(copies['items']), 1)

    def test_complete_backup_retains_history_recovery_and_new_clone_identity(self):
        from openhmi.workspace import ProjectWorkspace
        with TemporaryDirectory() as directory:
            workspace = ProjectWorkspace(Path(directory) / 'Original.openhmi.sqlite3')
            with TestClient(workspace) as client:
                initial = client.get('/api/project').json()
                self.apply(client, 'Recorded screen')
                copy = client.post('/api/project/recoveries', json={'base': initial['draft'], 'local': initial['draft'], 'base_revision': 1, 'reason': 'Backup candidate'})
                copy.raise_for_status()
                backup = client.get('/api/workspace/backup'); backup.raise_for_status()
                restored = client.post('/api/workspace/import?name=RestoredHistory', content=backup.content)
                self.assertEqual(restored.status_code, 200, restored.text)
                client.post('/api/workspace/open', json={'file': restored.json()['file']}).raise_for_status()
                self.assertNotEqual(client.get('/api/project').json()['project_id'], initial['project_id'])
                self.assertEqual(len(client.get('/api/project/revisions').json()['items']), 2)
                self.assertEqual(client.get('/api/project/recoveries/' + copy.json()['id']).json()['reason'], 'Backup candidate')
                self.assertTrue(workspace.current.state.driver.plc_hold)

    def test_corrupt_old_history_cannot_be_imported_and_original_is_preserved(self):
        from openhmi.workspace import ProjectWorkspace
        from fastapi import HTTPException
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'Original.openhmi.sqlite3'
            workspace = ProjectWorkspace(path)
            client = TestClient(workspace.current)  # No background SQL history writers for the byte preservation assertion.
            try:
                self.apply(client, 'Current valid revision')
                with workspace.current.state.store.transaction() as db:
                    db.execute("UPDATE project_revision SET content_hash='corrupt' WHERE revision=1")
                self.assertEqual(client.get('/api/project/revisions/1').status_code, 422)
                backup = workspace.export()
                before = path.read_bytes()
                with self.assertRaises(HTTPException) as failure:
                    workspace.import_backup('InvalidHistory', backup)
                self.assertEqual(failure.exception.status_code, 422)
                self.assertFalse((Path(directory) / 'InvalidHistory.openhmi.sqlite3').exists())
                self.assertEqual(path.read_bytes(), before)
            finally:
                client.close(); workspace.current.state.driver.close(); workspace.current.state.store.close()
