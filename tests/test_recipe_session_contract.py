"""Recipe authentication helpers through real local and HMI security services."""
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openhmi.projects import ProjectStore
from openhmi.recipe_routes import add_recipe_routes, Login, Empty, COOKIE as RECIPE_COOKIE
from openhmi.security import Security, COOKIE as HMI_COOKIE
from openhmi.security_routes import SecurityChange
from tests.test_frontend_contract import frontend
from tests.test_recipes import USERS, PASSWORD as RECIPE_PASSWORD
from tests.test_security import FakeWindows, PASSWORD as HMI_PASSWORD


def recipe_session_fixture(test_case, users=USERS):
    store = ProjectStore()
    test_case.addCleanup(store.close)
    driver = Mock(spec=['load_recipe', 'read'])
    driver.read.side_effect = AssertionError('Session contracts cannot read PLC tags')
    application = SimpleNamespace(lock=RLock(), driver=driver)
    security = Security(store, windows=FakeWindows())
    app = FastAPI()
    add_recipe_routes(app, store, application, users=users, security=security, commands=SimpleNamespace())
    client = TestClient(app)
    test_case.addCleanup(client.close)
    driver.reset_mock()
    return client, security, app.state.recipe_auth, driver


class RecipeSessionContractTests(unittest.TestCase):
    def fixture(self, users=USERS):
        return recipe_session_fixture(self, users)

    def browser(self, actions, **kwargs):
        return frontend('recipe_sessions', actions=actions, **kwargs)

    def send(self, client, request):
        self.assertTrue(request['timed'])
        self.assertEqual(request['headers']['X-OpenHMI-Project'], 'a' * 32)
        if 'method' not in request:
            self.assertEqual(request['path'], '/api/recipe-auth/session')
            return client.get(request['path'])
        self.assertEqual(request['method'], 'POST')
        model = Login if request['path'].endswith('login') else Empty
        model.model_validate(request['body'])
        return client.post(request['path'], json=request['body'])

    def test_recipe_local_cookie_rotation_expiry_logout_and_unconfigured_status(self):
        client, _, auth, driver = self.fixture()
        read, login, logout = self.browser([dict(action='read'), dict(action='login', name='engineer', password=RECIPE_PASSWORD),
                                           dict(action='logout')])['requests']
        self.assertEqual(self.send(client, read).json(), dict(configured=True, user=None))
        response = self.send(client, login)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        self.assertIn('SameSite=strict', response.headers['set-cookie'])
        token = client.cookies.get(RECIPE_COOKIE)
        user = self.send(client, read).json()['user']
        self.assertEqual(user, dict(name='engineer', roles=['approver', 'engineer', 'operator']))
        self.assertEqual(response.json()['user'], user)
        self.send(client, login).raise_for_status()
        self.assertNotEqual(token, client.cookies.get(RECIPE_COOKIE))
        self.assertIsNone(auth.user(token), 'Reauthentication invalidates the previous token')
        with auth.lock:
            auth.sessions = {key: (value[0], 0) for key, value in auth.sessions.items()}
        self.assertIsNone(self.send(client, read).json()['user'])
        self.assertEqual(self.send(client, logout).status_code, 401)
        self.send(client, login).raise_for_status()
        self.send(client, logout).raise_for_status()
        self.assertIsNone(client.cookies.get(RECIPE_COOKIE))
        self.assertIsNone(self.send(client, read).json()['user'])
        driver.read.assert_not_called()
        driver.load_recipe.assert_not_called()
        empty, _, _, _ = self.fixture(users={'users': []})
        self.assertEqual(self.send(empty, read).json(), dict(configured=False, user=None))

    def test_configured_hmi_identity_overrides_legacy_cookie_and_tracks_group_changes(self):
        client, security, _, driver = self.fixture()
        read, local_login, hmi_login, logout = self.browser([dict(action='read'),
            dict(action='login', name='engineer', password=RECIPE_PASSWORD),
            dict(action='login', name='engineer', password=HMI_PASSWORD), dict(action='logout')])['requests']
        self.send(client, local_login).raise_for_status()
        security.change(SecurityChange(operation='user', expected_version=security.snapshot()['version'],
            name='admin', groups=['Administrators'], password=HMI_PASSWORD, reason='Offline bootstrap'), 'test-console')
        def groups(names):
            security.change(SecurityChange(operation='user', expected_version=security.snapshot()['version'],
                name='engineer', groups=names, password=HMI_PASSWORD, reason='Offline HMI session fixture'), 'test-console')
        groups(['Operators'])
        self.assertEqual(self.send(client, read).json(), dict(configured=True, user=None))
        self.assertEqual(self.send(client, local_login).status_code, 401)
        response = self.send(client, hmi_login)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(HMI_COOKIE, response.headers['set-cookie'])
        user = self.send(client, read).json()['user']
        self.assertEqual((user['name'], user['provider'], user['roles']), ('engineer', 'local', ['operator']))
        self.assertEqual(response.json()['user'], user)
        self.assertEqual(set(user), {'name', 'provider', 'groups', 'permissions', 'roles'})
        security.change(SecurityChange(operation='group', expected_version=security.snapshot()['version'],
            name='Operators', permissions=['recipes.engineer'], reason='Offline role change'), 'test-console')
        self.assertIn('engineer', self.send(client, read).json()['user']['roles'])
        self.send(client, logout).raise_for_status()
        self.assertIsNone(client.cookies.get(HMI_COOKIE))
        self.assertIsNone(self.send(client, read).json()['user'], 'Legacy cookie cannot bypass HMI sign-out')
        driver.read.assert_not_called()
        driver.load_recipe.assert_not_called()

    def test_strict_login_logout_models_and_origin_checks_precede_authentication(self):
        client, security, auth, driver = self.fixture()
        auth.login = Mock(wraps=auth.login)
        security.login = Mock(wraps=security.login)
        operations = [dict(action='login', name=name, password=password) for name, password in
                      [('', RECIPE_PASSWORD), ('x' * 61, RECIPE_PASSWORD), (True, RECIPE_PASSWORD),
                       ('engineer', ''), ('engineer', 'x' * 257), ('engineer', False)]]
        for request in self.browser(operations)['requests']:
            self.assertEqual(client.post(request['path'], json=request['body']).status_code, 422)
        login, logout = self.browser([dict(action='login', name='engineer', password=RECIPE_PASSWORD), dict(action='logout')])['requests']
        for request in (login, logout):
            self.assertEqual(client.post(request['path'], json={**request['body'], 'roles': ['administrator']}).status_code, 422)
            self.assertEqual(client.post(request['path'], json=request['body'], headers={'Origin': 'https://example.invalid'}).status_code, 403)
        auth.login.assert_not_called()
        security.login.assert_not_called()
        self.assertEqual(auth.sessions, {})
        driver.read.assert_not_called()
        driver.load_recipe.assert_not_called()

    def test_request_fields_errors_and_optional_receipts_are_preserved_without_replay(self):
        actions = [dict(action='read'), dict(action='login', name=' Operator Δ ', password=' Synthetic password Δ '), dict(action='logout')]
        result = self.browser(actions)
        self.assertEqual(result['requests'][1]['body'], dict(name=actions[1]['name'], password=actions[1]['password']))
        self.assertEqual(result['requests'][2]['body'], {})
        for status in (401, 403, 422, 429, 503):
            result = self.browser(actions, status=status)
            self.assertEqual(len(result['requests']), 3)
            self.assertTrue(all(error == dict(error='Synthetic denial', status=status, operation_id='b' * 32,
                                              audit_status='denied') for error in result['results']))


if __name__ == '__main__':
    unittest.main()
