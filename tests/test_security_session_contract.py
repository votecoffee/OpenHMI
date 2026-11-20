"""Actual SQL-backed session responses accepted by the production browser guard."""
from copy import deepcopy
import json
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openhmi.projects import ProjectStore
from openhmi.security import Security
from openhmi.security_routes import SecurityChange, add_security_routes
from tests.test_frontend_contract import frontend
from tests.test_security import FakeWindows, PASSWORD


class SecuritySessionContractTests(unittest.TestCase):
    def service(self):
        store = ProjectStore()
        self.addCleanup(store.close)
        security = Security(store, windows=FakeWindows())
        app = FastAPI()
        add_security_routes(app, security)
        return security, TestClient(app)

    def change(self, security, operation, **values):
        return security.change(SecurityChange(operation=operation, expected_version=security.snapshot()['version'],
            reason='Offline session contract fixture', **values), 'offline-fixture')

    def test_actual_session_lifecycle_permissions_and_mock_windows_mapping(self):
        security, client = self.service()
        sessions = []
        def capture():
            response = client.get('/api/security/session')
            self.assertEqual(response.status_code, 200, response.text)
            identity = response.json()
            sessions.append(identity)
            return identity
        def login(name, provider='local'):
            reply = client.post('/api/security/login', json={'name': name, 'provider': provider, 'password': PASSWORD})
            self.assertEqual(reply.status_code, 200, reply.text)
        with client:
            self.assertFalse(capture()['configured'])
            security.windows.available = False
            self.assertFalse(capture()['windows_available'])
            security.windows.available = True
            self.change(security, 'user', name='admin', groups=['Administrators'], password=PASSWORD)
            self.assertIsNone(capture()['user'])
            login('admin')
            self.assertIn('security.manage', capture()['user']['permissions'])
            self.change(security, 'group', name='Session Operators', permissions=['runtime.operate'], color='#123456')
            self.change(security, 'user', name='operator', groups=['Session Operators'], password=PASSWORD)
            login('operator')
            self.assertEqual(capture()['user']['permissions'], ['runtime.operate'])
            self.change(security, 'group', name='Session Operators', permissions=[], color='#654321')
            self.assertEqual(capture()['user']['permissions'], [])
            client.post('/api/security/logout').raise_for_status()
            self.assertIsNone(capture()['user'])
            login('operator')
            with security.lock:
                security.sessions = {key: (value[0], 0) for key, value in security.sessions.items()}
            self.assertIsNone(capture()['user'])
            self.change(security, 'windows', enabled=True)
            self.change(security, 'binding', account='EXAMPLE\\Maintainers', kind='group', group='Engineers')
            self.change(security, 'binding', account='EXAMPLE\\person', kind='user', group='Approvers')
            login('EXAMPLE\\person', 'windows')
            identity = capture()
            self.assertEqual(identity['user']['provider'], 'windows')
            self.assertEqual(identity['user']['groups'], ['Approvers', 'Engineers'])
            self.assertIn('approver', identity['user']['roles'])
            self.change(security, 'windows', enabled=False)
            self.assertIsNone(capture()['user'])
        self.assertEqual(frontend('security_sessions', sessions=sessions), [True] * len(sessions))
        for identity in sessions:
            self.assertNotIn(PASSWORD, json.dumps(identity))
            if identity['user']:
                self.assertEqual(set(identity['user']), {'name', 'provider', 'groups', 'permissions', 'roles'})
            self.assertTrue(all(set(group) == {'name', 'color', 'permissions'} for group in identity['groups']))

    def test_malformed_payloads_rejected_without_mutation_or_coercion(self):
        _, client = self.service()
        with client:
            identity = client.get('/api/security/session').json()
        user = {'name': '设备 Operator', 'provider': 'local', 'groups': ['Operators'],
                'permissions': ['runtime.operate'], 'roles': []}
        configured = {**identity, 'configured': True, 'user': user}
        valid = [identity, configured, {**configured, 'user': {**user, 'provider': 'windows'}},
                 {**configured, 'user': None, 'groups': []}]
        malformed = [None, [], {}, {**identity, 'configured': 'false'},
            {**identity, 'windows_available': 1}, {**identity, 'windows_enabled': None},
            {**identity, 'user': user}, {**identity, 'groups': {}}, {**identity, 'groups': [None]},
            {**identity, 'groups': [{'name': 'Operators', 'color': '#123456', 'permissions': {}}]},
            *[{**configured, 'user': {**deepcopy(user), key: value}} for key, value in (
                ('name', None), ('provider', 'untrusted'), ('groups', {}),
                ('permissions', {}), ('roles', [None]))]]
        self.assertEqual(frontend('security_sessions', sessions=valid + malformed),
                         [True] * len(valid) + [False] * len(malformed))

    def test_read_helper_validates_success_and_preserves_http_errors(self):
        _, client = self.service()
        with client:
            identity = client.get('/api/security/session').json()
        result = frontend('security_session_read', response=identity)
        self.assertEqual(result['identity'], identity)
        self.assertEqual(result['requests'], [{'path': '/api/security/session', 'headers': {}, 'timed': True, 'method': 'GET'}])
        invalid = frontend('security_session_read', response={})
        self.assertEqual(invalid['error'], 'Invalid HMI identity status response')
        self.assertIsNone(invalid['status'])
        denied = frontend('security_session_read', response={'detail': 'Synthetic denial'}, status=403)
        self.assertEqual((denied['error'], denied['status']), ('Synthetic denial', 403))


if __name__ == '__main__':
    unittest.main()
