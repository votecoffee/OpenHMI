"""Consumed recipe session fields across real local and mocked Windows identities."""
import unittest

from openhmi.security import COOKIE
from openhmi.security_routes import SecurityChange
from tests.test_frontend_contract import frontend
from tests.test_recipe_session_contract import recipe_session_fixture, RECIPE_PASSWORD, HMI_PASSWORD


class RecipeSessionResponseTests(unittest.TestCase):
    def validate(self, entries):
        return frontend('recipe_session_responses', entries=entries)

    def test_actual_local_login_expiry_logout_and_unconfigured_replies(self):
        client, _, auth, driver = recipe_session_fixture(self)
        entries = []
        def capture(kind, response):
            self.assertEqual(response.status_code, 200, response.text)
            entries.append(dict(kind=kind, data=response.json()))
        capture('session', client.get('/api/recipe-auth/session'))
        capture('login', client.post('/api/recipe-auth/login', json={'name': 'engineer', 'password': RECIPE_PASSWORD}))
        capture('session', client.get('/api/recipe-auth/session'))
        with auth.lock:
            auth.sessions = {key: (value[0], 0) for key, value in auth.sessions.items()}
        capture('session', client.get('/api/recipe-auth/session'))
        capture('login', client.post('/api/recipe-auth/login', json={'name': 'engineer', 'password': RECIPE_PASSWORD}))
        capture('logout', client.post('/api/recipe-auth/logout', json={}))
        empty, _, _, _ = recipe_session_fixture(self, users={'users': []})
        capture('session', empty.get('/api/recipe-auth/session'))
        self.assertEqual(self.validate(entries), [dict(valid=True, same=True)] * len(entries))
        driver.read.assert_not_called()
        driver.load_recipe.assert_not_called()

    def test_hmi_public_identity_windows_mapping_and_empty_roles_remain_compatible(self):
        client, security, _, driver = recipe_session_fixture(self)
        def change(operation, **values):
            security.change(SecurityChange(operation=operation, expected_version=security.snapshot()['version'],
                reason='Offline session response fixture', **values), 'test-console')
        change('user', name='admin', groups=['Administrators'], password=HMI_PASSWORD)
        login = client.post('/api/recipe-auth/login', json={'name': 'admin', 'password': HMI_PASSWORD})
        self.assertEqual(login.status_code, 200, login.text)
        entries = [dict(kind='login', data=login.json()), dict(kind='session', data=client.get('/api/recipe-auth/session').json())]
        change('windows', enabled=True)
        change('binding', account='EXAMPLE\\Maintainers', kind='group', group='Engineers')
        token, _ = security.login('EXAMPLE\\person', HMI_PASSWORD, 'fixture-peer', provider='windows')
        client.cookies.set(COOKIE, token)
        identity = client.get('/api/recipe-auth/session').json()
        self.assertEqual(identity['user']['provider'], 'windows')
        entries.append(dict(kind='session', data=identity))
        change('group', name='Engineers', permissions=[])
        no_roles = client.get('/api/recipe-auth/session').json()
        self.assertEqual(no_roles['user']['roles'], [])
        entries.append(dict(kind='session', data=no_roles))
        self.assertEqual(self.validate(entries), [dict(valid=True, same=True)] * len(entries))
        driver.read.assert_not_called()
        driver.load_recipe.assert_not_called()

    def test_malformed_roles_names_and_confirmation_fields_are_rejected_without_mutation(self):
        valid = [dict(kind='session', data=dict(configured=True, user=None)),
                 dict(kind='session', data=dict(configured=False, user=None)),
                 dict(kind='login', data={'user': {'name': 'Legacy', 'roles': ['engineer', 'future-role']}}),
                 dict(kind='session', data={'configured': True, 'user': {'name': 'HMI', 'roles': [], 'extra': {'kept': True}}}),
                 dict(kind='logout', data={'ok': True, 'extra': 'kept'})]
        invalid = [dict(kind='session', data=value) for value in (None, {}, dict(configured='true', user=None),
            dict(configured=False, user={'name': 'Unexpected', 'roles': []}),
            dict(configured=True, user={'name': 'Bad', 'roles': {}}), dict(configured=True, user={'name': [], 'roles': []}))]
        invalid += [dict(kind='login', data=value) for value in ({}, {'user': None}, {'user': {'name': 'Bad', 'roles': [None]}})]
        invalid += [dict(kind='logout', data=value) for value in (None, {}, {'ok': 'true'}, {'ok': False})]
        outcome = self.validate(valid + invalid)
        self.assertEqual(outcome[:len(valid)], [dict(valid=True, same=True)] * len(valid))
        self.assertTrue(all(item['valid'] is False for item in outcome[len(valid):]))


if __name__ == '__main__':
    unittest.main()
