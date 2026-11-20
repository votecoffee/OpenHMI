"""Real SQL/HTTP project library responses against production JS contracts."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError
from openhmi.workspace import ProjectWorkspace
from openhmi.workspace_contracts import LibrarySnapshot, CreatedProject, ImportedProject, OpenedProject
from tests.test_frontend_contract import frontend


class WorkspaceContractTests(unittest.TestCase):
    def fixture(self):
        directory = self.enterContext(TemporaryDirectory())
        workspace = ProjectWorkspace(Path(directory) / '设备🚀.sqlite3', hold_connections=True)
        client = self.enterContext(TestClient(workspace))
        return workspace, client

    def test_real_listing_models_cover_arbitrary_current_names_and_reject_incoherent_data(self):
        workspace, client = self.fixture()
        workspace.create('Another', 'Another machine')
        response = client.get('/api/workspace')
        self.assertEqual(response.status_code, 200, response.text)
        good = response.json()
        LibrarySnapshot.model_validate(good)
        self.assertEqual(good['current'], '设备🚀.sqlite3')
        invalid = [None, {}, {**good, 'projects': []}, {**good, 'projects': [None]}, {**good, 'handlers': 1},
                   {**good, 'plc_hold': None}, {**good, 'current': '../outside'}, {**good, 'current': 'absent.sqlite3'},
                   {**good, 'projects': good['projects'] * 2}]
        for flag in (None, 1, False):
            data = deepcopy(good)
            for row in data['projects']: row['current'] = flag
            invalid.append(data)
        for data in invalid:
            with self.assertRaises(ValidationError): LibrarySnapshot.model_validate(data)
        self.assertEqual(frontend('workspace_library', libraries=[good, *invalid])['libraries'], [True] + [False] * len(invalid))

    def test_real_create_import_open_acknowledgements_and_browser_serializers_agree(self):
        workspace, client = self.fixture()
        backup = workspace.export()
        requests = [dict(kind='create', name='Created', title='设备 machine'),
                    dict(kind='import', name='Imported', bytes=list(backup)),
                    dict(kind='open', file='Created.openhmi.sqlite3')]
        replies = [{'data': {'file': 'Created.openhmi.sqlite3'}},
                   {'data': {'file': 'Imported.openhmi.sqlite3', 'handlers_saved_for_review': False, 'plc_hold': True}},
                   {'data': {'ok': True, 'current': 'Created.openhmi.sqlite3'}}]
        generated = frontend('workspace_operations', requests=requests, replies=replies)
        results = []
        with patch.object(workspace, 'create', wraps=workspace.create) as create, \
             patch.object(workspace, 'import_backup', wraps=workspace.import_backup) as import_backup, \
             patch.object(workspace, 'open', wraps=workspace.open) as open_project:
            for request, call, model in zip(requests, generated['calls'], (CreatedProject, ImportedProject, OpenedProject)):
                self.assertEqual(call['method'], 'POST')
                self.assertTrue(call['timed'])
                if request['kind'] == 'import':
                    self.assertEqual(call['headers']['Content-Type'], 'application/zip')
                    self.assertEqual(bytes(call['bytes']), backup)
                    response = client.post(call['path'], content=bytes(call['bytes']), headers=call['headers'])
                else:
                    self.assertEqual(call['headers']['Content-Type'], 'application/json')
                    response = client.post(call['path'], json=call['body'])
                self.assertEqual(response.status_code, 200, response.text)
                data = response.json(); model.model_validate(data)
                expected = request.get('file', request.get('name', '') + '.openhmi.sqlite3')
                results.append(dict(data=data, kind=request['kind'], expected=expected))
            create.assert_called_once(); import_backup.assert_called_once(); open_project.assert_awaited_once()
        self.assertEqual(frontend('workspace_library', results=results)['results'], [True, True, True])
        self.assertEqual(frontend('workspace_operations', requests=requests, replies=[{'data': item['data']} for item in results])['results'],
                         [{'data': item['data']} for item in results])
        self.assertEqual(workspace.path.name, 'Created.openhmi.sqlite3')

    def test_malformed_or_mismatched_acknowledgements_preserve_review_guidance_without_replay(self):
        requests, replies = [], []
        cases = [('create', {'file': 'Expected.openhmi.sqlite3'}, {'file': 'Different.openhmi.sqlite3'}),
                 ('import', {'file': 'Expected.openhmi.sqlite3', 'handlers_saved_for_review': False, 'plc_hold': True},
                  {'file': 'Expected.openhmi.sqlite3', 'handlers_saved_for_review': False, 'plc_hold': False}),
                 ('open', {'ok': True, 'current': 'Expected.openhmi.sqlite3'}, {'ok': True, 'current': 'Different.openhmi.sqlite3'})]
        validations = []
        for kind, good, wrong in cases:
            expected = 'Expected.openhmi.sqlite3'
            validations += [dict(data=good, kind=kind, expected=expected), dict(data=wrong, kind=kind, expected=expected)]
            for reply in ({'data': None}, {'data': {}}, {'data': wrong}, {'raw': 'invalid JSON'}):
                requests.append(dict(kind=kind, name='Expected', title='Draft title', file=expected, bytes=[0, 255, 1]))
                replies.append(reply)
        self.assertEqual(frontend('workspace_library', results=validations)['results'], [True, False] * 3)
        result = frontend('workspace_operations', requests=requests, replies=replies)
        self.assertEqual(len(result['calls']), len(requests))
        self.assertTrue(all(item['requiresReview'] and 'Refresh the project library' in item['error'] for item in result['results']))
        with self.assertRaises(ValidationError): ImportedProject(file='Expected.openhmi.sqlite3', handlers_saved_for_review=False, plc_hold=1)
        with self.assertRaises(ValidationError): OpenedProject(ok=False, current='Expected.openhmi.sqlite3')

    def test_normal_http_errors_and_encoded_import_name_do_not_retry(self):
        statuses = [401, 403, 409, 422, 503]
        result = frontend('workspace_operations', requests=[dict(kind='create', name='Expected', title='Draft') for _ in statuses],
                          replies=[{'status': status, 'data': {'detail': 'Synthetic denial'}} for status in statuses])
        self.assertEqual(len(result['calls']), len(statuses))
        self.assertEqual([item['status'] for item in result['results']], statuses)
        self.assertEqual([item['requiresReview'] for item in result['results']], [False, False, False, False, True])
        self.assertTrue(all(item['error'] == 'Synthetic denial' for item in result['results'][:-1]))
        encoded = frontend('workspace_operations', requests=[dict(kind='import', name='设备 /,+%?&#', bytes=[0, 255, 1])],
                           replies=[{'status': 422, 'data': {'detail': 'Invalid ID'}}])
        from urllib.parse import parse_qs, urlsplit
        self.assertEqual(parse_qs(urlsplit(encoded['calls'][0]['path']).query), {'name': ['设备 /,+%?&#']})
        self.assertEqual(encoded['calls'][0]['bytes'], [0, 255, 1])
