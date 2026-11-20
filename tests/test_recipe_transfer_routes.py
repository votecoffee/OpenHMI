"""Standalone transfer HTTP boundaries with an in-memory activity journal."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from openhmi.activity import ActivityJournal
from openhmi.projects import ProjectStore
from openhmi.recipe_auth import RecipeUser
from openhmi.recipe_transfer_routes import add_recipe_transfer_routes


class RecipeTransferRouteTests(unittest.TestCase):
    def fixture(self):
        store = ProjectStore()
        self.addCleanup(store.close)
        principal = RecipeUser('Fixture Engineer', frozenset({'engineer'}))
        security = SimpleNamespace(configured=Mock(return_value=False), user=Mock(return_value=None), require=Mock())
        auth = SimpleNamespace(user=Mock(return_value=principal))
        user = Mock(return_value=principal)
        transfers = SimpleNamespace(recent=Mock(return_value={'items': []}), get=Mock(return_value={'id': 7}), submit=Mock())
        activity = ActivityJournal(store, security)
        app = FastAPI()
        add_recipe_transfer_routes(app, transfers, store, auth, security, activity, user,
                                   lambda method, *args: method(*args))
        client = TestClient(app)
        self.addCleanup(client.close)
        return client, transfers, store, activity, security, auth, user

    def body(self):
        return {'revision_id': 9, 'expected_revision_version': 2, 'reason': 'Offline fixture', 'expected_project_revision': 4}

    def test_history_export_and_validation_boundaries(self):
        client, transfers, store, _, _, _, user = self.fixture()
        self.assertEqual(client.get('/api/recipe-transfers').status_code, 200)
        transfers.recent.assert_called_once_with(25, None, '', None, '')
        response = client.get('/api/recipe-transfers', params={'limit': 100, 'before_id': '9223372036854775807',
                              'profile_id': '设备,+%', 'production_approved': 'false', 'verified_profile': 'proof'})
        self.assertEqual(response.status_code, 200)
        transfers.recent.assert_called_with(100, 9223372036854775807, '设备,+%', False, 'proof')
        for query in ('limit=0', 'limit=101', 'before_id=9223372036854775808', 'profile_id=' + 'x' * 61):
            self.assertEqual(client.get('/api/recipe-transfers?' + query).status_code, 422)
        self.assertEqual(client.get('/api/recipe-transfers/0').status_code, 422)
        transfers.get.assert_not_called()
        response = client.get('/api/recipe-transfers/7?download=true')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual(response.headers['content-disposition'], 'attachment; filename="openhmi-recipe-transfer-7.json"')
        exported = response.json()
        self.assertEqual((exported['format'], exported['version'], exported['project_id'], exported['transfer']),
                         ('openhmi.recipe-transfer', 1, store.snapshot()['project_id'], {'id': 7}))
        self.assertTrue(exported['exported_at'])
        self.assertEqual(client.get('/api/recipe-transfers/7').json(), {'id': 7})
        transfers.get.reset_mock(); transfers.recent.reset_mock()
        user.return_value = RecipeUser('No roles', frozenset())
        self.assertEqual(client.get('/api/recipe-transfers').status_code, 403)
        self.assertEqual(client.get('/api/recipe-transfers/7').status_code, 403)
        transfers.get.assert_not_called(); transfers.recent.assert_not_called()

    def test_dispatch_journals_identity_before_authorization_and_dispatch(self):
        client, transfers, _, activity, security, auth, user = self.fixture()
        def submit(profile, body, current, ticket, authorize):
            row = activity.query()['items'][0]
            self.assertEqual((row['status'], row['phase'], row['actor'], row['provider'], row['groups']),
                             ('pending', 'prepared', 'Fixture Engineer', 'recipe-local', ['recipe:engineer']))
            self.assertEqual(row['context'], {'revision_id': 9, 'reason': 'Offline fixture', 'expected_project_revision': 4})
            self.assertEqual(profile, 'product')
            self.assertIs(current, user.return_value)
            self.assertEqual(body.expected_revision_version, 2)
            authorize({'security_groups': []})
            security.require.assert_not_called()
            authorize({'security_groups': ['Engineers']})
            self.assertEqual(security.require.call_args.args[1:], ('runtime.operate', ['Engineers']))
            ticket.dispatch()
            self.assertEqual(activity.query()['items'][0]['phase'], 'dispatch_started')
            ticket.confirm(verification='offline-fixture')
            return {'id': 7}
        transfers.submit.side_effect = submit
        client.cookies.set('openhmi_recipe_session', 'fixture')
        response = client.post('/api/recipe-transfers/product/dispatch', json=self.body())
        self.assertEqual(response.status_code, 200, response.text)
        auth.user.assert_called_once_with('fixture')
        row = activity.query()['items'][0]
        self.assertEqual((row['status'], row['outcome']['verification']), ('succeeded', 'offline-fixture'))
        # HMI accounts supply journal identity; recipe-local auth must be bypassed.
        auth.user.reset_mock(); security.require.reset_mock(); security.configured.return_value = True
        security.user.return_value = SimpleNamespace(name='Windows Engineer', provider='windows', groups=['Engineers'])
        def hmi_submit(profile, body, current, ticket, authorize):
            authorize({'security_groups': []})
            return {'id': 8}
        transfers.submit.side_effect = hmi_submit
        self.assertEqual(client.post('/api/recipe-transfers/product/dispatch', json=self.body()).status_code, 200)
        auth.user.assert_not_called()
        self.assertEqual(security.require.call_args.args[1:], ('runtime.operate', []))
        row = activity.query()['items'][0]
        self.assertEqual((row['actor'], row['provider'], row['groups']), ('Windows Engineer', 'windows', ['Engineers']))

    def test_validation_authorization_and_journal_failure_prevent_dispatch(self):
        client, transfers, _, activity, _, _, user = self.fixture()
        self.assertEqual(client.post('/api/recipe-transfers/product/dispatch', json={**self.body(), 'revision_id': '9'}).status_code, 422)
        self.assertEqual(activity.query()['items'], [])
        user.side_effect = HTTPException(401, 'Sign in first')
        self.assertEqual(client.post('/api/recipe-transfers/product/dispatch', json=self.body()).status_code, 401)
        self.assertEqual((activity.query()['items'][0]['status'], activity.query()['items'][0]['phase']), ('denied', 'prepared'))
        transfers.submit.assert_not_called()
        user.reset_mock(); user.side_effect = None
        with patch.object(activity, 'start', side_effect=sqlite3.OperationalError('offline failure')):
            self.assertEqual(client.post('/api/recipe-transfers/product/dispatch', json=self.body()).status_code, 503)
        user.assert_not_called(); transfers.submit.assert_not_called()

    def test_focused_import_does_not_construct_service_or_load_server(self):
        code = "import json,sys; import openhmi.recipe_transfer_routes; print(json.dumps([name for name in ('openhmi.recipe_routes','openhmi.recipes','openhmi.recipe_transfers','openhmi.server','pycomm3') if name in sys.modules]))"
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=30, check=True)
        self.assertEqual(json.loads(result.stdout), [])
