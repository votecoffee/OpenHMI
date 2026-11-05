"""Edit limit enforcement and opt-in PLC identity status, all offline/synthetic."""
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from openhmi.server import create_app
from tests.test_security import bootstrap, PASSWORD


class TouchSecurityTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.addCleanup(self.app.state.store.close)
        self.client = TestClient(self.app)

    def install(self, change):
        state = self.client.get('/api/project').json()
        change(state['draft'])
        saved = self.client.put('/api/project/draft', json={'expected_revision': state['draft_revision'], 'project': state['draft']})
        self.assertEqual(saved.status_code, 200, saved.text)
        result = self.client.post('/api/project/apply', json={'expected_revision': saved.json()['draft_revision']})
        self.assertEqual(result.status_code, 200, result.text)

    def edits(self, project):
        project['tags'] += [{'name': 'Low', 'type': 'number', 'initial': 10.0, 'writable': True}, {'name': 'High', 'type': 'number', 'initial': 50.0, 'writable': True}, {'name': 'Length', 'type': 'integer', 'initial': 4, 'writable': True}]
        project['controls'] += [{'id': 'number_edit', 'kind': 'input', 'label': 'Number', 'tag': 'TankLevel', 'minimum_tag': 'Low', 'maximum_tag': 'High'},
                                {'id': 'text_edit', 'kind': 'text_input', 'label': 'Text', 'tag': 'OperatorText', 'min_length': 1, 'max_length_tag': 'Length'},
                                {'id': 'who', 'kind': 'current_user', 'label': 'Operator'}]

    def test_dynamic_numeric_bounds_are_enforced_at_dispatch(self):
        self.install(self.edits)
        path = '/api/controls/number_edit/value'
        self.assertEqual(self.client.put(path, json={'value': 25.0}).status_code, 200)
        self.app.state.driver.write('High', [20.0])
        with patch.object(self.app.state.driver, 'write') as write:
            self.assertEqual(self.client.put(path, json={'value': 25.0}).status_code, 422)
            write.assert_not_called()
        self.app.state.driver._tags['High'] = None
        self.assertEqual(self.client.put(path, json={'value': 15.0}).status_code, 409)
        self.app.state.driver._tags['High'] = 5.0
        self.assertEqual(self.client.put(path, json={'value': 15.0}).status_code, 409)

    def test_text_bounds_unicode_and_wrong_types(self):
        self.install(self.edits)
        path = '/api/controls/text_edit/value'
        for value in ('', 'abcde', 12, True, 'a\x00'):
            self.assertEqual(self.client.put(path, json={'value': value}).status_code, 422)
        self.assertEqual(self.client.put(path, json={'value': '😀中文a'}).status_code, 200)
        self.app.state.driver.write('Length', [2])
        self.assertEqual(self.client.put(path, json={'value': 'abc'}).status_code, 422)
        self.assertEqual(self.client.put(path, json={'value': '中文'}).status_code, 200)

    def test_stale_edit_revision_cannot_write_to_rebound_control(self):
        self.install(self.edits)
        previous_revision = self.client.get('/api/project/active').json()['revision']

        def rebind(project):
            project['tags'].append({'name': 'NewNumber', 'type': 'number', 'initial': 15, 'writable': True})
            next(control for control in project['controls'] if control['id'] == 'number_edit')['tag'] = 'NewNumber'

        self.install(rebind)
        path = '/api/controls/number_edit/value'
        with patch.object(self.app.state.driver, 'write') as write:
            rejected = self.client.put(path, json={'value': 25, 'expected_revision': previous_revision})
            self.assertEqual(rejected.status_code, 409)
            self.assertIn('applied project changed', rejected.json()['detail'])
            write.assert_not_called()
        revision = self.client.get('/api/project/active').json()['revision']
        self.assertEqual(self.client.put(path, json={'value': 25, 'expected_revision': revision}).status_code, 200)
        self.assertEqual(self.app.state.driver.read('NewNumber'), [25])

    def test_bound_tags_participate_in_screen_and_udt_demands(self):
        self.install(self.edits)
        self.app.state.driver.lease('synthetic', ['overview'])
        demands = self.app.state.driver.demands(__import__('time').monotonic())
        self.assertIn('Low', demands); self.assertIn('High', demands); self.assertIn('Length', demands)
        from openhmi.screens import expanded_controls
        project = self.client.get('/api/project').json()['active']
        project['tags'].append({'name': 'Device', 'type': 'struct'})
        project['faceplates'] = [{'id': 'template', 'controls': [{'id': 'edit', 'kind': 'input', 'tag': '$.Value', 'minimum_tag': '$.Low', 'maximum_tag': '$.High'}]}]
        project['controls'] = [{'id': 'device', 'kind': 'faceplate', 'template': 'template', 'root_tag': 'Device'}]
        item = expanded_controls(project)[0]
        self.assertEqual((item['minimum_tag'], item['maximum_tag']), ('Device.Low', 'Device.High'))

    def setup_publication(self, remote=False):
        bootstrap(self.app)
        self.client.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD}).raise_for_status()
        def configure(project):
            project['tags'] += [{'name': 'LoginName', 'type': 'string', 'initial': '', 'writable': True}, {'name': 'LoginBits', 'type': 'integer', 'initial': 0, 'writable': True}]
            if remote:
                project['connections'] = [{'id': 'plc', 'name': 'Synthetic', 'path': 'offline-only/0', 'enabled': True}]
                for tag in project['tags'][-2:]:
                    tag.update(connection='plc', address=tag['name'])
            project['identity_publication'] = {'enabled': True, 'username_tag': 'LoginName', 'privileges_tag': 'LoginBits', 'username_bytes': 82,
                'bits': [{'bit': 0, 'source': 'permission', 'name': 'runtime.write'}, {'bit': 31, 'source': 'group', 'name': 'Administrators'}]}
        self.install(configure)
        return self.app.state.identity_publisher

    def test_fake_plc_string_and_dint_metadata_are_checked_before_publication(self):
        from tests.test_logix_history import FakePLC
        class IdentityPLC(FakePLC):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.tags.update(LoginName={'external_access': 'Read/Write', 'data_type': {'name': 'STRING', 'string': 82}}, LoginBits={'external_access': 'Read/Write', 'data_type': 'DINT'})
                self.values.update(LoginName='', LoginBits=0)
        self.app.state.driver.factory = IdentityPLC
        publisher = self.setup_publication(remote=True)
        self.app.state.driver.poll()
        self.client.post('/api/security/publication/claim', json={'client': 'a'}).raise_for_status()
        publisher.poll()
        plc = self.app.state.driver.connections['plc'].client
        self.assertEqual(plc.values['LoginBits'], -2147483647)
        self.assertEqual(plc.values['LoginName'], 'admin')
        plc.tags['LoginBits']['data_type'] = 'INT'
        publisher.applied = None
        before = len(plc.writes); publisher.poll()
        self.assertEqual(len(plc.writes), before)
        self.assertEqual(publisher.snapshot()['status'], 'error')
        self.addCleanup(self.app.state.driver.close)

    def test_failed_username_write_does_not_grant_privilege_bits(self):
        publisher = self.setup_publication()
        self.client.post('/api/security/publication/claim', json={'client': 'a'}).raise_for_status()
        original = self.app.state.driver._write
        def fail_name(tag, values):
            if tag == 'LoginName':
                raise ConnectionError('Synthetic interrupted username write')
            return original(tag, values)
        with patch.object(self.app.state.driver, '_write', side_effect=fail_name):
            publisher.poll()
        self.assertEqual(self.app.state.driver.read('LoginBits'), [0])
        self.assertEqual(publisher.snapshot()['status'], 'error')

    def test_optional_heartbeat_advances_after_a_complete_status_write(self):
        publisher = self.setup_publication()
        # Add the optional heartbeat through the reviewed project contract.
        def configure(project):
            project['tags'].append({'name': 'IdentityHeartbeat', 'type': 'integer', 'initial': 0, 'writable': True})
            project['identity_publication']['heartbeat_tag'] = 'IdentityHeartbeat'
        self.install(configure)
        self.client.post('/api/security/publication/claim', json={'client': 'a'}).raise_for_status()
        publisher.poll()
        first = self.app.state.driver.read('IdentityHeartbeat')[0]
        publisher.last_write = 0; publisher.poll()
        self.assertGreater(self.app.state.driver.read('IdentityHeartbeat')[0], first)

    def test_nonadministrator_cannot_change_publication_contract(self):
        self.setup_publication()
        from openhmi.security_routes import SecurityChange
        security = self.app.state.security
        security.change(SecurityChange(operation='user', name='engineer', password=PASSWORD, groups=['Engineers'], expected_version=security.snapshot()['version'], reason='Synthetic engineer'), 'test-console')
        self.client.post('/api/security/login', json={'name': 'engineer', 'password': PASSWORD}).raise_for_status()
        state = self.client.get('/api/project').json()
        state['draft']['identity_publication']['username_bytes'] = 100
        self.assertEqual(self.client.put('/api/project/draft', json={'expected_revision': state['draft_revision'], 'project': state['draft']}).status_code, 403)

    def test_claim_publish_word_order_signed_bit31_and_logout(self):
        publisher = self.setup_publication()
        publisher.poll()
        self.assertEqual(self.app.state.driver.read('LoginBits'), [0])
        self.client.post('/api/security/publication/claim', json={'client': 'station-a'}).raise_for_status()
        with patch.object(self.app.state.driver, '_write', wraps=self.app.state.driver._write) as writes:
            publisher.poll()
            self.assertEqual([call.args for call in writes.call_args_list], [('LoginBits', [0]), ('LoginName', ['admin']), ('LoginBits', [-2147483647])])
        self.assertEqual(self.app.state.driver.read('LoginName'), ['admin'])
        with self.assertRaisesRegex(ValueError, 'runtime-owned'):
            self.app.state.driver.write('LoginBits', [123])
        self.client.post('/api/security/logout', json={}).raise_for_status(); publisher.poll()
        self.assertEqual(self.app.state.driver.read('LoginBits'), [0])
        self.assertEqual(self.app.state.driver.read('LoginName'), [''])

    def test_station_conflict_expiry_revocation_and_hold(self):
        publisher = self.setup_publication()
        self.client.post('/api/security/publication/claim', json={'client': 'station-a'}).raise_for_status()
        other = TestClient(self.app)
        other.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD}).raise_for_status()
        self.assertEqual(other.post('/api/security/publication/claim', json={'client': 'station-b'}).status_code, 409)
        publisher.poll(); publisher.deadline = 0; publisher.poll()
        self.assertEqual(self.app.state.driver.read('LoginBits'), [0])
        other.post('/api/security/publication/claim', json={'client': 'station-b'}).raise_for_status()
        self.app.state.driver.plc_hold = True
        with patch.object(self.app.state.driver, '_write') as writes:
            publisher.poll(); writes.assert_not_called()
        self.assertEqual(publisher.snapshot()['status'], 'held')
        self.app.state.driver.plc_hold = False
        publisher.poll()
        self.app.state.security.sessions.clear(); publisher.poll()
        self.assertEqual(self.app.state.driver.read('LoginBits'), [0])

    def test_publication_capacity_failure_and_disabled_default(self):
        publisher = self.app.state.identity_publisher
        with patch.object(self.app.state.driver, '_write') as writes:
            publisher.poll(); writes.assert_not_called()
        publisher = self.setup_publication()
        self.client.post('/api/security/publication/claim', json={'client': 'a'}).raise_for_status()
        self.app.state.driver.project['identity_publication']['username_bytes'] = 2
        publisher.poll()
        self.assertEqual(publisher.snapshot()['status'], 'error')
        self.assertEqual(self.app.state.driver.read('LoginBits'), [0])

    def test_group_colors_and_legend_are_persistent_but_do_not_grant_access(self):
        bootstrap(self.app)
        self.client.post('/api/security/login', json={'name': 'admin', 'password': PASSWORD}).raise_for_status()
        response = self.client.put('/api/security', json={'operation': 'group', 'name': 'Maintenance', 'permissions': ['runtime.write'], 'color': '#123456', 'expected_version': self.app.state.security.snapshot()['version'], 'reason': 'Synthetic style'})
        self.assertEqual(response.status_code, 200, response.text)
        group = next(item for item in self.client.get('/api/security/session').json()['groups'] if item['name'] == 'Maintenance')
        self.assertEqual(group['color'], '#123456')
        self.assertEqual(group['permissions'], ['runtime.write'])
