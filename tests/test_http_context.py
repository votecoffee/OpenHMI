"""Request identity and durable receipts across runtime/workspace/JS boundaries."""
from contextlib import nullcontext
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from openhmi.server import create_app
from openhmi.workspace import ProjectWorkspace
from tests.test_frontend_contract import frontend


class HttpContextTests(unittest.TestCase):
    def fixture(self):
        app = create_app()
        self.addCleanup(app.state.store.close)
        self.addCleanup(app.state.driver.close)
        app.state.driver.factory = Mock(side_effect=AssertionError('Offline test cannot open a PLC connection'))
        client = TestClient(app)  # No lifespan/background acquisition.
        self.addCleanup(client.close)
        return app, client

    def wire(self, response):
        return dict(status=response.status_code, headers=dict(response.headers), body=response.text)

    def test_runtime_guard_precedes_handler_and_read_methods_remain_compatible(self):
        app, client = self.fixture()
        handled = Mock(return_value={'ok': True})
        @app.api_route('/context-target', methods=['GET', 'HEAD', 'OPTIONS', 'POST', 'PUT', 'PATCH', 'DELETE'])
        def target():
            return handled()
        instance = app.state.project_instance
        for method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            response = client.request(method, '/context-target', headers={'X-OpenHMI-Project': 'old-instance'})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.headers['X-OpenHMI-Project'], instance)
            self.assertNotIn('X-OpenHMI-Operation-ID', response.headers)
            self.assertIn('Reload before making changes', response.json()['detail'])
        handled.assert_not_called()
        self.assertEqual(app.state.activity.query()['items'], [])
        for method in ('GET', 'HEAD', 'OPTIONS'):
            response = client.request(method, '/context-target', headers={'X-OpenHMI-Project': 'old-instance'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['X-OpenHMI-Project'], instance)
        for headers in ({}, {'X-OpenHMI-Project': ''}, {'X-OpenHMI-Project': instance}):
            self.assertEqual(client.post('/context-target', headers=headers).status_code, 200)
        self.assertEqual(handled.call_count, 6)
        # Stale writes are rejected even before ordinary model validation.
        self.assertEqual(client.post('/api/project/apply', json={}, headers={'X-OpenHMI-Project': 'old-instance'}).status_code, 409)
        for path, status in (('/missing', 404), ('/api/project/apply', 422)):
            response = client.post(path, json={})
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.headers['X-OpenHMI-Project'], instance)
        app.state.driver.factory.assert_not_called()

    def test_journal_outcomes_reach_http_and_actual_js_without_replay(self):
        app, client = self.fixture()
        dispatched = Mock()
        @app.post('/context-operation/{kind}')
        def operation(kind: str, request: Request):
            def execute(ticket):
                if kind == 'denied': raise HTTPException(403, 'No permission')
                if kind == 'rejected': raise HTTPException(422, 'Invalid operation')
                ticket.dispatch()
                dispatched()
                if kind == 'uncertain': raise HTTPException(409, 'Synthetic transport failure')
                ticket.confirm(verification='offline-fixture')
                return {'ok': True}
            return app.state.activity.run(request, 'fixture', kind, {}, execute)
        replies = [self.wire(client.get('/api/project'))]
        requests = [dict(path='/api/project')]
        expected = [('success', 200, 'succeeded'), ('denied', 403, 'denied'),
                    ('rejected', 422, 'rejected'), ('uncertain', 409, 'uncertain'), ('pending', 200, 'pending')]
        for kind, status, audit in expected:
            with (patch.object(app.state.activity, 'finish', side_effect=sqlite3.OperationalError('Offline finalization outage'))
                  if kind == 'pending' else nullcontext()):
                with self.assertLogs(level='ERROR') if kind == 'pending' else nullcontext():
                    response = client.post('/context-operation/' + kind)
            self.assertEqual(response.status_code, status, response.text)
            self.assertEqual(response.headers['X-OpenHMI-Project'], app.state.project_instance)
            self.assertEqual(response.headers['X-OpenHMI-Audit-Status'], audit)
            row = app.state.activity.query()['items'][0]
            self.assertEqual(response.headers['X-OpenHMI-Operation-ID'], row['operation_id'])
            self.assertEqual(row['status'], audit)
            replies.append(self.wire(response))
            requests.append(dict(path='/context-operation/' + kind, options={'method': 'POST'}))
        result = frontend('http_context', requests=requests, replies=replies)
        self.assertEqual(len(result['calls']), len(requests))
        for index, (_, status, audit) in enumerate(expected, 1):
            outcome = result['results'][index]
            data = outcome['data'] if status == 200 else outcome
            self.assertEqual((data['operation_id'], data['audit_status']),
                             (replies[index]['headers']['x-openhmi-operation-id'], audit))
            if status != 200:
                self.assertEqual((outcome['status'], outcome['conflict']), (status, status == 409))
        self.assertEqual(dispatched.call_count, 3)
        self.assertEqual(len(app.state.activity.query()['items']), 5)
        app.state.driver.factory.assert_not_called()

    def test_replacement_identity_header_never_rebinds_browser_or_retries_write(self):
        app, client = self.fixture()
        old = 'a' * 32
        initial = self.wire(client.get('/api/project'))
        initial['body'] = '{"project_instance":"' + old + '"}'
        response = client.post('/api/controls/toggle/activate', json={}, headers={'X-OpenHMI-Project': old})
        self.assertEqual(response.status_code, 409)
        reply = self.wire(response)
        requests = [dict(path='/api/project'), dict(path='/api/controls/toggle/activate', options={'method': 'POST'}),
                    dict(path='/api/project'), dict(path='/api/controls/toggle/activate', options={'method': 'POST'})]
        result = frontend('http_context', requests=requests,
                          replies=[initial, reply, self.wire(client.get('/api/project')), reply])
        self.assertEqual(len(result['calls']), 4)
        for call in result['calls'][1:]:
            self.assertEqual(call['headers']['X-OpenHMI-Project'], old)
        for index in (1, 3):
            self.assertTrue(result['results'][index]['conflict'])
            self.assertIsNone(result['results'][index]['operation_id'])
            self.assertIsNone(result['results'][index]['audit_status'])
        self.assertEqual(app.state.activity.query()['items'], [])
        app.state.driver.factory.assert_not_called()

    def test_workspace_errors_share_identity_guard_and_headers(self):
        with TemporaryDirectory() as directory:
            workspace = ProjectWorkspace(Path(directory) / 'Fixture.openhmi.sqlite3')
            app = workspace.current
            self.addCleanup(app.state.store.close)
            self.addCleanup(app.state.driver.close)
            app.state.driver.factory = Mock(side_effect=AssertionError('Offline test cannot open a PLC connection'))
            with TestClient(workspace) as client:
                # This workspace test starts only the default simulator.
                instance = workspace.current.state.project_instance
                with patch.object(workspace, 'handle', wraps=workspace.handle) as handle:
                    response = client.post('/api/workspace/create', json={'name': 'Stale', 'title': 'Stale'},
                                           headers={'X-OpenHMI-Project': 'old-instance'})
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(response.headers['X-OpenHMI-Project'], instance)
                    handle.assert_not_called()
                self.assertFalse((Path(directory) / 'Stale.openhmi.sqlite3').exists())
                for method, path, content, status in [('GET', '/api/workspace', None, 200),
                    ('POST', '/api/workspace/create', 'invalid JSON', 422),
                    ('POST', '/api/workspace/unknown', None, 404)]:
                    response = client.request(method, path, content=content)
                    self.assertEqual(response.status_code, status, response.text)
                    self.assertEqual(response.headers['X-OpenHMI-Project'], instance)
                    self.assertNotIn('X-OpenHMI-Operation-ID', response.headers)
                app.state.driver.factory.assert_not_called()
