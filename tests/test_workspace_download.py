"""Complete backup HTTP/body contracts; synthetic SQL only, no controllers."""
from io import BytesIO
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient
from openhmi.workspace import ProjectWorkspace, MAX_BACKUP
from tests.test_frontend_contract import frontend


class WorkspaceDownloadTests(unittest.TestCase):
    def fixture(self, users=None):
        directory = self.enterContext(TemporaryDirectory())
        workspace = ProjectWorkspace(Path(directory) / 'Original.openhmi.sqlite3', recipe_users=users, hold_connections=True)
        self.addCleanup(workspace.current.state.store.close)
        self.addCleanup(workspace.current.state.driver.close)
        client = TestClient(workspace)
        self.addCleanup(client.close)
        return workspace, client

    def wire(self, response):
        return dict(status=response.status_code, headers=dict(response.headers), bytes=list(response.content))

    def test_real_backup_headers_bytes_manifest_and_actual_browser_helper_agree(self):
        workspace, client = self.fixture()
        response = client.get('/api/workspace/backup')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        self.assertEqual(int(response.headers['content-length']), len(response.content))
        with zipfile.ZipFile(BytesIO(response.content)) as archive:
            self.assertIsNone(archive.testzip())
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(manifest['files'], {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist() if name != 'manifest.json'})
        result = frontend('workspace_backup', projectInstance=workspace.current.state.project_instance,
                          zips=[list(response.content)], replies=[self.wire(response)])
        self.assertEqual(result['maximum'], MAX_BACKUP)
        self.assertEqual(result['valid'], [True])
        self.assertEqual(bytes(result['results'][0]['bytes']), response.content)
        self.assertEqual(result['results'][0]['filename'], 'project.openhmi.zip')
        self.assertEqual(result['calls'], [dict(path='/api/workspace/backup', method='GET', cache='no-store', timed=True,
                          headers={'X-OpenHMI-Project': workspace.current.state.project_instance})])

    def test_permission_stale_context_and_export_errors_are_private_and_prevent_dispatch(self):
        from tests.test_recipes import USERS, PASSWORD
        from tests.test_security import bootstrap, PASSWORD as HMI_PASSWORD
        workspace, client = self.fixture(USERS)
        with patch.object(workspace, 'export', wraps=workspace.export) as export:
            denied = client.get('/api/workspace/backup')
            self.assertEqual(denied.status_code, 403)
            client.post('/api/recipe-auth/login', json={'name': 'engineer', 'password': PASSWORD}).raise_for_status()
            self.assertEqual(client.get('/api/workspace/backup').status_code, 403)
            export.assert_not_called()
            client.post('/api/recipe-auth/login', json={'name': 'manager', 'password': PASSWORD}).raise_for_status()
            self.assertEqual(client.get('/api/workspace/backup').status_code, 200)
        with patch.object(workspace, 'export', side_effect=AssertionError('Stale context cannot export')) as export:
            stale = client.get('/api/workspace/backup', headers={'X-OpenHMI-Project': 'a' * 32})
            self.assertEqual(stale.status_code, 409); export.assert_not_called()
        bootstrap(workspace.current)
        no_session = client.get('/api/workspace/backup')
        self.assertEqual(no_session.status_code, 401)
        client.post('/api/security/login', json={'name': 'admin', 'password': HMI_PASSWORD}).raise_for_status()
        with patch.object(workspace, 'export', side_effect=OSError('Private filesystem marker')), self.assertLogs(level='ERROR'):
            failed = client.get('/api/workspace/backup')
        self.assertEqual(failed.status_code, 503)
        self.assertNotIn('Private filesystem marker', failed.text)
        for response in (denied, stale, no_session, failed):
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
            self.assertNotIn('content-disposition', response.headers)
        replies = [self.wire(item) for item in (denied, stale, no_session, failed)]
        result = frontend('workspace_backup', projectInstance=workspace.current.state.project_instance, replies=replies)
        self.assertEqual([row['status'] for row in result['results']], [403, 409, 401, 503])
        self.assertTrue(all('filename' not in row for row in result['results']))
        self.assertEqual(len(result['calls']), 4)

    def test_malformed_headers_partial_zip_and_stream_overflow_never_produce_a_download(self):
        workspace, client = self.fixture()
        response = client.get('/api/workspace/backup')
        good = self.wire(response)
        instance = workspace.current.state.project_instance
        bad = []
        for key, value in [('content-type', 'text/html'), ('content-disposition', 'attachment; filename="../bad.zip"'),
                           ('content-length', 'invalid'), ('content-length', str(len(response.content) + 1)),
                           ('content-length', str(MAX_BACKUP + 1)), ('x-openhmi-project', 'f' * 32)]:
            bad.append({**good, 'headers': {**good['headers'], key: value}})
        bad += [{**good, 'status': 206}, {**good, 'bytes': list(response.content[:-8])},
                {**good, 'bytes': list(b'<html>error</html>')}, {**good, 'networkError': 'Offline network interruption'}]
        stream_headers = {key: value for key, value in good['headers'].items() if key != 'content-length'}
        bad.append({'headers': stream_headers, 'overflow': True})
        result = frontend('workspace_backup', projectInstance=instance, replies=bad)
        self.assertEqual(len(result['calls']), len(bad))
        self.assertTrue(all('error' in row and 'filename' not in row for row in result['results']))
        self.assertIn('download limit', result['results'][-1]['error'])
        # Chunked responses without Content-Length remain bounded and valid.
        result = frontend('workspace_backup', projectInstance=instance, replies=[{**good, 'headers': stream_headers}])
        self.assertEqual(bytes(result['results'][0]['bytes']), response.content)

    def test_zip_framing_rejects_unsupported_or_incoherent_packages(self):
        workspace, client = self.fixture()
        good = client.get('/api/workspace/backup').content
        unknown = BytesIO()
        with zipfile.ZipFile(unknown, 'w') as archive:
            archive.writestr('manifest.json', '{}'); archive.writestr('project.sqlite3', b'fixture'); archive.writestr('../outside', b'no')
        end = good.rfind(b'PK\x05\x06')
        changed = bytearray(good); changed[end + 16:end + 20] = (0).to_bytes(4, 'little')
        result = frontend('workspace_backup', zips=[list(good), [], list(good[:-1]), list(unknown.getvalue()), list(changed)])
        self.assertEqual(result['valid'], [True, False, False, False, False])

    def test_exported_zip_size_is_bounded_even_after_compression_overhead(self):
        workspace, client = self.fixture()
        class OversizedZip:
            def __init__(self, output, *args, **kwargs): self.output = output
            def __enter__(self): return self
            def writestr(self, *args, **kwargs): pass
            def __exit__(self, *args): self.output.write(b'x' * (1024 * 1024 + 1))
        with patch('openhmi.workspace.MAX_BACKUP', 1024 * 1024), patch('openhmi.workspace.zipfile.ZipFile', OversizedZip):
            response = client.get('/api/workspace/backup')
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertNotIn('content-disposition', response.headers)
