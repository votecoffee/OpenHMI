"""Metadata-only inventory HTTP/SQL-to-JS contracts; never reads PLCs."""
from copy import deepcopy
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError
from openhmi.workspace import ProjectWorkspace
from openhmi.workspace_inventory import ArtifactPage, ArtifactQuery, LibraryArtifact, RULES, inventory
from openhmi.workspace_publication import companion_paths
from tests.test_frontend_contract import frontend


class WorkspaceInventoryTests(unittest.TestCase):
    def fixture(self, recipe_users=None):
        directory = self.enterContext(TemporaryDirectory())
        workspace = ProjectWorkspace(Path(directory) / 'Original.openhmi.sqlite3', recipe_users=recipe_users, hold_connections=True)
        self.addCleanup(workspace.current.state.store.close)
        self.addCleanup(workspace.current.state.driver.close)
        workspace.current.state.driver.factory = Mock(side_effect=AssertionError('Offline test cannot connect to PLC'))
        client = TestClient(workspace)
        self.addCleanup(client.close)
        return workspace, client

    def test_metadata_inventory_matches_publication_guards_and_never_reads_contents(self):
        workspace, client = self.fixture()
        # Authorization reads the active database. Keep synthetic journal files
        # beside an inactive entry so SQLite cannot consume them during that read.
        original = workspace.root / 'Associated.openhmi.sqlite3'
        original.write_bytes(b'Inventory must not inspect database contents')
        expected = companion_paths(original)
        for index, path in enumerate(expected):
            path.write_bytes(b'Private content must never be returned ' + str(index).encode())
        orphan = workspace.root / 'Orphan.openhmi.hold'
        orphan.write_bytes(b'private orphan')
        directory = workspace.root / 'Folder.openhmi.handlers.py'
        directory.mkdir()
        (directory / 'do-not-traverse.txt').write_bytes(b'private nested content')
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('Inventory cannot read file contents')), \
             patch.object(Path, 'open', side_effect=AssertionError('Inventory cannot open files')), \
             patch('sqlite3.connect', side_effect=AssertionError('Inventory cannot open databases')):
            response = client.get('/api/workspace/artifacts')
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        ArtifactPage.model_validate(data)
        rows = {item['file']: item for item in data['items']}
        self.assertEqual(len(rows), 8)
        self.assertEqual({rows[path.name]['kind'] for path in expected}, {kind for _, kind in RULES})
        self.assertTrue(all(rows[path.name]['project_entry_type'] == 'file' for path in expected))
        self.assertEqual(rows[orphan.name]['project_entry_type'], 'missing')
        self.assertEqual((rows[directory.name]['entry_type'], rows[directory.name]['size_bytes']), ('directory', None))
        self.assertNotIn('Private content', response.text)
        self.assertNotIn(str(workspace.root), response.text)
        self.assertEqual(response.headers['X-OpenHMI-Project'], workspace.current.state.project_instance)
        self.assertEqual(frontend('workspace_artifacts', pages=[{'data': data}])['valid'], [True])
        workspace.current.state.driver.factory.assert_not_called()

    def test_actual_browser_queries_page_unicode_names_and_validate_bounds(self):
        workspace, client = self.fixture()
        for name in ('A', '设备', '\ue000', '\U0001f680'):
            (workspace.root / (name + '.openhmi.hold')).write_bytes(b'x')
        queries = [{'limit': 2}, {'limit': 2, 'after': '设备.openhmi.hold'},
                   {'limit': 1, 'after': '设备 /,+%?&#'}]
        paths = frontend('workspace_artifacts', queries=queries)['paths']
        first = client.get(paths[0]); self.assertEqual(first.status_code, 200)
        page = first.json()
        self.assertEqual([item['file'] for item in page['items']], ['A.openhmi.hold', '设备.openhmi.hold'])
        second = client.get(paths[1]).json()
        self.assertEqual([item['file'] for item in second['items']], ['\ue000.openhmi.hold', '\U0001f680.openhmi.hold'])
        self.assertIsNone(second['next_after'])
        self.assertEqual(frontend('workspace_artifacts', pages=[{'data': page}, {'data': second, 'after': page['next_after']}])['valid'], [True, True])
        self.assertEqual(client.get(paths[2]).status_code, 422)
        with patch('openhmi.workspace.inventory', side_effect=AssertionError('Invalid query cannot scan files')):
            for params in ({'limit': 0}, {'limit': 101}, {'after': '../outside'}, {'after': 'x' * 256}, {'contents': 'true'}):
                self.assertEqual(client.get('/api/workspace/artifacts', params=params).status_code, 422)
        self.assertEqual(client.post('/api/workspace/artifacts').status_code, 404)

    def test_scan_bounds_and_metadata_failures_do_not_follow_links_or_report_a_complete_scan(self):
        workspace, client = self.fixture()
        path = workspace.root / 'Link.openhmi.hold'
        path.write_bytes(b'not read')
        lstat = Path.lstat
        def metadata(candidate):
            if candidate == path:
                return SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
            return lstat(candidate)
        with patch.object(Path, 'lstat', new=metadata), patch.object(Path, 'stat', side_effect=AssertionError('Do not follow links')):
            page = inventory(workspace.root, ArtifactQuery())
        row = page['items'][0]
        self.assertEqual((row['entry_type'], row['size_bytes']), ('link', None))
        with patch('openhmi.workspace_inventory.MAX_SCANNED_ENTRIES', 1):
            limited = client.get('/api/workspace/artifacts').json()
        self.assertTrue(limited['scan_limited'])
        def unavailable(candidate):
            if candidate == path:
                raise PermissionError('Private metadata failure')
            return lstat(candidate)
        with patch.object(Path, 'lstat', new=unavailable):
            row = client.get('/api/workspace/artifacts').json()['items'][0]
        self.assertEqual((row['entry_type'], row['size_bytes']), ('unavailable', None))
        with patch('openhmi.workspace_inventory.os.scandir', side_effect=PermissionError('Private root marker')), self.assertLogs(level='ERROR'):
            failure = client.get('/api/workspace/artifacts')
        self.assertEqual(failure.status_code, 503)
        self.assertNotIn('Private root marker', failure.text)
        self.assertEqual(client.get('/api/workspace/artifacts').status_code, 200)

    def test_unrepresentable_names_are_skipped_with_an_incomplete_inventory_flag(self):
        workspace, _ = self.fixture()
        entries = Mock()
        entries.__enter__ = Mock(return_value=iter([SimpleNamespace(name='\udcff.openhmi.hold')]))
        entries.__exit__ = Mock(return_value=False)
        with patch('openhmi.workspace_inventory.os.scandir', return_value=entries):
            page = inventory(workspace.root, ArtifactQuery())
        self.assertEqual(page, {'items': [], 'next_after': None, 'scan_limited': True})
        self.assertTrue(frontend('workspace_artifacts', pages=[{'data': page}])['valid'][0])

    def test_python_and_browser_reject_incoherent_response_contracts(self):
        workspace, client = self.fixture()
        (workspace.root / 'Fixture.openhmi.hold').write_bytes(b'x')
        good = client.get('/api/workspace/artifacts').json()
        invalid = [None, {}, {**deepcopy(good), 'scan_limited': None}, {**deepcopy(good), 'next_after': 'wrong'},
                   {**deepcopy(good), 'items': good['items'] * 2}]
        for key, value in [('file', '../outside'), ('project_file', 'Wrong.openhmi.sqlite3'), ('kind', 'unknown'),
                           ('entry_type', 'unknown'), ('project_entry_type', 'unknown'), ('size_bytes', True),
                           ('size_bytes', 2**53), ('size_bytes', -1)]:
            data = deepcopy(good); data['items'][0][key] = value; invalid.append(data)
        data = deepcopy(good); data['items'][0]['entry_type'] = 'directory'; invalid.append(data)
        for data in invalid:
            with self.assertRaises(ValidationError):
                ArtifactPage.model_validate(data)
        results = frontend('workspace_artifacts', pages=[{'data': good}] + [{'data': item} for item in invalid])['valid']
        self.assertEqual(results, [True] + [False] * len(invalid))
        self.assertFalse(frontend('workspace_artifacts', pages=[{'data': good, 'after': good['items'][0]['file']}])['valid'][0])
        # Derived project names can be longer than their artifact's native filename.
        row = {**good['items'][0], 'file': 'x' * 240 + '.openhmi.hold', 'project_file': 'x' * 240 + '.openhmi.sqlite3'}
        LibraryArtifact.model_validate(row)
        self.assertTrue(frontend('workspace_artifacts', pages=[{'data': {'items': [row], 'next_after': None, 'scan_limited': False}}])['valid'][0])

    def test_inventory_is_protected_by_hmi_and_legacy_administrator_permissions(self):
        from tests.test_recipes import USERS, PASSWORD
        from tests.test_security import bootstrap, PASSWORD as HMI_PASSWORD
        workspace, client = self.fixture(USERS)
        with patch('openhmi.workspace.inventory', wraps=inventory) as scan:
            self.assertEqual(client.get('/api/workspace/artifacts').status_code, 403)
            client.post('/api/recipe-auth/login', json={'name': 'engineer', 'password': PASSWORD}).raise_for_status()
            self.assertEqual(client.get('/api/workspace/artifacts').status_code, 403)
            scan.assert_not_called()
            client.post('/api/recipe-auth/login', json={'name': 'manager', 'password': PASSWORD}).raise_for_status()
            self.assertEqual(client.get('/api/workspace/artifacts').status_code, 200)
            bootstrap(workspace.current)
            self.assertEqual(client.get('/api/workspace/artifacts').status_code, 401)
            client.post('/api/security/login', json={'name': 'admin', 'password': HMI_PASSWORD}).raise_for_status()
            self.assertEqual(client.get('/api/workspace/artifacts').status_code, 200)
        workspace.current.state.driver.factory.assert_not_called()
