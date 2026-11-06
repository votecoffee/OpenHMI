"""Authorization boundaries; all identities and passwords here are synthetic."""

from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from openhmi.server import create_app
from openhmi.security_routes import SecurityChange
from openhmi.windows_identity import enabled_group

PASSWORD = 'SecurityTestOnly-2026!'


def bootstrap(app):
    service = app.state.security
    service.change(SecurityChange(operation='user', expected_version=service.snapshot()['version'],
                                 name='admin', groups=['Administrators'], password=PASSWORD, reason='Synthetic test bootstrap'), 'test-console')


class FakeWindows:
    available = True

    def resolve(self, name, kind):
        return {'EXAMPLE\\Maintainers': 'S-1-5-21-100-200', 'EXAMPLE\\person': 'S-1-5-21-100-101'}[name]

    def authenticate(self, name, password):
        if password != PASSWORD:
            return None
        return {'name': name, 'sid': 'S-1-5-21-100-101', 'groups': ['S-1-5-21-100-200']}


class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        bootstrap(self.app)
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.login()

    def login(self, name='admin', provider='local'):
        result = self.client.post('/api/security/login', json={'name': name, 'password': PASSWORD, 'provider': provider})
        self.assertEqual(result.status_code, 200, result.text)
        return result

    def change(self, operation, **kwargs):
        return self.client.put('/api/security', json={'operation': operation, 'expected_version': self.app.state.security.snapshot()['version'], 'reason': 'Synthetic security change', **kwargs})

    def user(self, name, groups):
        result = self.change('user', name=name, groups=groups, password=PASSWORD)
        self.assertEqual(result.status_code, 200, result.text)

    def test_mode_requests_use_the_applied_allowlist_and_separate_feedback(self):
        state = self.client.get('/api/project').json()
        draft = state['draft']
        draft['tags'] += [
            {'name': 'ModeRequest', 'type': 'integer', 'initial': 0, 'writable': True},
            {'name': 'ModeFeedback', 'type': 'integer', 'initial': 0},
            {'name': 'ModePermit', 'type': 'boolean', 'initial': True, 'writable': True},
        ]
        modes = [{'value': 0, 'label': 'Manual'}, {'value': 1, 'label': 'Auto'}]
        selector = {'id': 'mode', 'kind': 'mode_selector', 'label': 'Machine mode',
                    'tag': 'ModeRequest', 'confirmed_tag': 'ModeFeedback', 'states': modes,
                    'enabled_tag': 'ModePermit', 'security_groups': ['Administrators']}
        draft['controls'] += [
            selector, {'id': 'state', 'kind': 'multi_state', 'label': 'State', 'tag': 'ModeFeedback', 'states': modes},
            {'id': 'permissives', 'kind': 'permissives', 'label': 'Permissives',
             'checks': [{'tag': 'ModePermit', 'label': 'Mode change allowed'}]},
        ]
        selector['confirmed_tag'] = 'ModeRequest'
        rejected = self.client.put('/api/project/draft', json={'expected_revision': state['draft_revision'], 'project': draft})
        self.assertEqual(rejected.status_code, 422)
        self.assertIn('separate tags', rejected.text)
        selector['confirmed_tag'] = 'ModeFeedback'
        saved = self.client.put('/api/project/draft', json={'expected_revision': state['draft_revision'], 'project': draft})
        saved.raise_for_status()
        applied = self.client.post('/api/project/apply', json={'expected_revision': saved.json()['draft_revision']})
        applied.raise_for_status()
        revision = applied.json()['active_revision']
        url = '/api/controls/mode/value'
        self.assertEqual(self.client.put(url, json={'value': 1}).status_code, 422)
        self.assertEqual(self.client.put(url, json={'value': 3, 'expected_revision': revision}).status_code, 422)
        self.assertEqual(self.client.put(url, json={'value': 1, 'expected_revision': revision - 1}).status_code, 409)

        driver = self.app.state.driver
        driver.write('ModePermit', [False])
        request = {'value': 1, 'expected_revision': revision}
        self.assertEqual(self.client.put(url, json=request).status_code, 423)
        driver.write('ModePermit', [True])
        values = driver.snapshot()
        values.pop('ModeFeedback')
        with patch.object(driver, 'snapshot', return_value=values):
            self.assertEqual(self.client.put(url, json=request).status_code, 409)
        self.client.put(url, json=request).raise_for_status()
        self.assertEqual(driver.read('ModeRequest'), [1])
        self.assertEqual(driver.read('ModeFeedback'), [0])

        self.client.post('/api/security/logout').raise_for_status()
        self.assertEqual(self.client.put(url, json=request).status_code, 401)

    def test_palette_inputs_validate_tag_bindings_and_reject_unlisted_writes(self):
        state = self.client.get('/api/project').json()
        draft = state['draft']
        draft['tags'] += [
            {'name': 'Choice', 'type': 'integer', 'initial': 0, 'writable': True},
            {'name': 'Flag', 'type': 'boolean', 'initial': False, 'writable': True},
            {'name': 'Notes', 'type': 'string', 'initial': '', 'writable': True},
        ]
        dropdown = {'id': 'choice', 'kind': 'dropdown', 'tag': 'Choice', 'label': 'Choice',
                    'options': [{'value': 0, 'label': 'Low'}, {'value': 1, 'label': 'High'}],
                    'enabled_tag': 'Flag', 'security_groups': ['Administrators']}
        draft['controls'] += [
            dropdown, {'id': 'flag', 'kind': 'toggle_switch', 'tag': 'Flag', 'label': 'Flag'},
            {'id': 'notes', 'kind': 'text_area', 'tag': 'Notes', 'label': 'Notes', 'max_length': 4},
        ]

        def save():
            return self.client.put('/api/project/draft', json={'expected_revision': state['draft_revision'], 'project': draft})

        dropdown['tag'] = 'Flag'
        self.assertEqual(save().status_code, 422)
        dropdown['tag'] = 'Choice'
        draft['tags'][-3]['writable'] = False
        self.assertEqual(save().status_code, 422)
        draft['tags'][-3]['writable'] = True
        saved = save()
        saved.raise_for_status()
        applied = self.client.post('/api/project/apply', json={'expected_revision': saved.json()['draft_revision']})
        applied.raise_for_status()
        revision = applied.json()['active_revision']

        def write(control, value, expected=revision):
            return self.client.put(f'/api/controls/{control}/value', json={'value': value, 'expected_revision': expected})

        self.assertEqual(write('flag', True, None).status_code, 422)
        self.assertEqual(write('flag', True, revision - 1).status_code, 409)
        self.assertEqual(write('flag', 1).status_code, 422)
        self.assertEqual(write('choice', 1).status_code, 423)
        write('flag', True).raise_for_status()
        for invalid in (True, 1.0, '1', 2):
            self.assertEqual(write('choice', invalid).status_code, 422)
        self.assertEqual(write('notes', 'AB\nCD').status_code, 422)
        driver = self.app.state.driver
        values = driver.snapshot()
        values.pop('Choice')
        with patch.object(driver, 'snapshot', return_value=values):
            self.assertEqual(write('choice', 1).status_code, 409)
        write('choice', 1).raise_for_status()
        write('notes', 'A\n文').raise_for_status()
        self.assertEqual(driver.read('Choice'), [1])
        self.assertEqual(driver.read('Notes'), ['A\n文'])
        self.client.post('/api/security/logout').raise_for_status()
        self.assertEqual(write('choice', 0).status_code, 401)

    def controls(self):
        state = self.client.get('/api/project').json()
        project = state['draft']
        project['controls'][2]['security_groups'] = ['Maintenance']
        project['controls'].append({'id': 'setpoint', 'kind': 'input', 'label': 'Setpoint', 'tag': 'TankLevel', 'minimum': 0.0, 'maximum': 100.0, 'security_groups': ['Maintenance']})
        result = self.client.put('/api/project/draft', json={'project': project, 'expected_revision': state['draft_revision']})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.post('/api/project/apply', json={'expected_revision': result.json()['draft_revision']}).status_code, 200)

    def test_local_groups_control_actions_values_and_other_mutations(self):
        self.assertEqual(self.change('group', name='Maintenance', permissions=['runtime.operate', 'runtime.write']).status_code, 200)
        self.user('maint', ['Maintenance'])
        self.user('operator', ['Operators'])
        self.controls()
        self.client.post('/api/security/logout')
        self.assertEqual(self.client.post('/api/actions/toggle_motor', json={'control_id': 'toggle'}).status_code, 401)
        self.login('operator')
        for payload in ({}, {'control_id': 'toggle'}):
            self.assertEqual(self.client.post('/api/actions/toggle_motor', json=payload).status_code, 403)
        self.assertEqual(self.client.put('/api/controls/setpoint/value', json={'value': 25.0}).status_code, 403)
        self.assertEqual(self.client.put('/api/security', json={'operation': 'group', 'expected_version': 1, 'name': 'Hack', 'reason': 'Not allowed'}).status_code, 403)
        self.assertEqual(self.client.post('/api/project/apply', json={'expected_revision': 1}).status_code, 403)
        self.assertEqual(self.client.post('/api/alarms/acknowledge-all', json={}).status_code, 200)
        self.login('maint')
        self.assertEqual(self.client.post('/api/actions/toggle_motor', json={'control_id': 'toggle'}).status_code, 200)
        self.assertFalse(self.app.state.driver.read('MotorRunning')[0])
        self.assertEqual(self.client.put('/api/controls/setpoint/value', json={'value': 25.0}).status_code, 200)
        self.assertEqual(self.app.state.driver.read('TankLevel'), [25.0])
        self.assertEqual(self.client.put('/api/controls/setpoint/value', json={'value': 101.0}).status_code, 422)
        self.assertEqual(self.client.put('/api/controls/level/value', json={'value': 25.0}).status_code, 404)
        self.assertEqual(self.client.post('/api/actions/toggle_motor', json={'control_id': 'alarm'}).status_code, 404)
        self.assertEqual(self.client.post('/api/alarms/acknowledge-all', json={}).status_code, 403)

    def test_revocation_expiry_disable_and_last_administrator(self):
        self.user('operator', ['Operators'])
        other = TestClient(self.app)
        other.post('/api/security/login', json={'name': 'operator', 'password': PASSWORD})
        self.assertEqual(self.change('group', name='Operators', permissions=[]).status_code, 200)
        self.assertEqual(other.post('/api/alarms/acknowledge-all', json={}).status_code, 403)
        self.assertEqual(self.change('user', name='operator', groups=['Operators'], enabled=False).status_code, 200)
        self.assertIsNone(other.get('/api/security/session').json()['user'])
        self.assertEqual(self.change('user', name='admin', groups=[], enabled=False).status_code, 409)
        self.assertEqual(self.change('group', name='Administrators', permissions=[]).status_code, 409)
        self.assertEqual(self.client.get('/api/security').status_code, 200)
        security = self.app.state.security
        with security.lock:
            security.sessions = {key: (identity, time.monotonic() - 1) for key, (identity, _) in security.sessions.items()}
        self.assertEqual(self.client.post('/api/actions/toggle_motor', json={}).status_code, 401)
        self.assertEqual(self.client.post('/api/security/logout').status_code, 200)

    def test_windows_user_and_group_mappings_use_authenticated_sids(self):
        self.app.state.security.windows = FakeWindows()
        self.assertEqual(self.change('windows', enabled=True).status_code, 200)
        self.assertEqual(self.client.post('/api/security/login', json={'name': 'EXAMPLE\\person', 'password': PASSWORD, 'provider': 'windows'}).status_code, 401)
        self.assertEqual(self.change('binding', account='EXAMPLE\\Maintainers', kind='group', group='Engineers').status_code, 200)
        result = self.login('EXAMPLE\\person', 'windows')
        self.assertEqual(result.json()['user']['groups'], ['Engineers'])
        self.assertIn('project.edit', result.json()['user']['permissions'])
        self.assertEqual(self.client.post('/api/security/login', json={'name': 'person', 'password': 'wrong', 'provider': 'windows', 'groups': ['Administrators']}).status_code, 422)
        self.login()
        self.assertEqual(self.change('binding', account='EXAMPLE\\person', kind='user', group='Approvers').status_code, 200)
        self.login('EXAMPLE\\person', 'windows')
        self.assertIn('approver', self.client.get('/api/recipe-auth/session').json()['user']['roles'])
        self.login()
        self.assertEqual(self.change('unbind', sid='S-1-5-21-100-200', kind='group', group='Engineers').status_code, 200)
        self.assertEqual(self.change('windows', enabled=False).status_code, 200)
        self.assertEqual(self.client.post('/api/security/login', json={'name': 'EXAMPLE\\person', 'password': PASSWORD, 'provider': 'windows'}).status_code, 401)
        self.assertTrue(enabled_group(4))
        for flags in (0, 2, 16, 20):
            self.assertFalse(enabled_group(flags))

    def test_security_persistence_conflicts_origin_and_private_configuration(self):
        state = self.app.state.security.snapshot()
        self.assertEqual(self.change('group', name='ReadOnly', permissions=['bogus']).status_code, 422)
        result = self.client.put('/api/security', json={'operation': 'group', 'expected_version': state['version'] - 1, 'name': 'ReadOnly', 'reason': 'Stale request'})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.client.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD}, headers={'Origin': 'https://foreign.invalid'}).status_code, 403)
        self.assertNotIn('password_hash', self.client.get('/api/security').text)
        self.client.post('/api/security/logout')
        self.assertEqual(self.client.get('/api/security').status_code, 401)
        self.assertEqual(self.client.put('/api/project/draft', json={'project': self.client.get('/api/project').json()['draft'], 'expected_revision': 1}).status_code, 401)
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'project.sqlite3'
            app = create_app(path)
            bootstrap(app)
            with TestClient(app) as client:
                client.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD})
                old_cookie = client.cookies.get('openhmi_session')
            with TestClient(create_app(path)) as client:
                self.assertTrue(client.get('/api/security/session').json()['configured'])
                client.cookies.set('openhmi_session', old_cookie)
                self.assertEqual(client.get('/api/security').status_code, 401)
                self.assertEqual(client.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD}).status_code, 200)

    def test_rate_limit_shared_across_names_and_providers(self):
        for index in range(10):
            self.assertEqual(self.client.post('/api/security/login', json={'name': f'unknown{index}', 'password': 'incorrect', 'provider': 'local' if index % 2 else 'windows'}).status_code, 401)
        self.assertEqual(self.client.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD}).status_code, 429)

    def test_unified_recipe_identity_rejects_legacy_session_bypass(self):
        from tests.test_recipes import recipe_content
        self.user('author', ['Engineers', 'Approvers'])
        self.login('author')
        created = self.client.post('/api/recipes', json={'code': 'SECURE-A', 'content': recipe_content(), 'reason': 'Unified HMI identity'})
        self.assertEqual(created.status_code, 200, created.text)
        identifier = created.json()['id']
        submitted = self.client.post(f'/api/recipe-revisions/{identifier}/transition', json={'expected_version': 1, 'action': 'submit', 'reason': 'Ready for review'})
        approved = self.client.post(f'/api/recipe-revisions/{identifier}/transition', json={'expected_version': submitted.json()['version'], 'action': 'approve', 'reason': 'Author is also approver'})
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(approved.json()['approved_by'], 'author')
        legacy = self.app.state.recipe_auth
        encoded = self.app.state.security.store._db.execute('SELECT password_hash FROM security_user WHERE name=?', ('author',)).fetchone()[0]
        legacy.users['rogue'] = {'name': 'rogue', 'roles': ['administrator'], 'password_hash': encoded}
        token = legacy.login('rogue', PASSWORD, 'synthetic')
        self.client.post('/api/security/logout')
        self.client.cookies.set('openhmi_recipe_session', token)
        self.assertEqual(self.client.post('/api/recipes', json={'code': 'BYPASS', 'content': recipe_content(), 'reason': 'Must be denied'}).status_code, 401)
        self.assertIsNone(self.client.get('/api/recipe-auth/session').json()['user'])
