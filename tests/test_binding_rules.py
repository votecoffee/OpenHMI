"""Observable rule precedence and rejected-draft preservation through the API."""
import copy
import unittest

from fastapi.testclient import TestClient
from openhmi.server import create_app


class BindingRuleTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(hold_connections=True))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        state = self.client.get('/api/project').json()
        project = copy.deepcopy(state['draft'])
        project['tags'].append({'name': 'RuleRequest', 'type': 'integer', 'initial': 2, 'writable': True})
        saved = self.client.put('/api/project/draft', json={
            'expected_revision': state['draft_revision'], 'project': project})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.state = self.client.get('/api/project').json()

    def reject(self, project, detail):
        result = self.client.put('/api/project/draft', json={
            'expected_revision': self.state['draft_revision'], 'project': project})
        self.assertEqual(result.status_code, 422, result.text)
        self.assertEqual(result.json()['detail'], detail)
        self.assertEqual(self.client.get('/api/project').json(), self.state)

    def test_common_guards_precede_edit_type_checks(self):
        project = copy.deepcopy(self.state['draft'])
        control = {'id': 'entry', 'kind': 'stepper', 'label': 'Request', 'tag': 'RuleRequest',
                   'step': 0.5, 'minimum_tag': 'MotorRunning', 'enabled_tag': 'TankLevel',
                   'security_groups': ['MissingGroup']}
        project['controls'] = [control]
        self.reject(project, 'Edit limits require an existing numeric tag')
        del control['minimum_tag']
        self.reject(project, 'Conditional bindings require a Boolean tag')
        del control['enabled_tag']
        self.reject(project, 'Control references an unknown HMI security group')
        control['security_groups'] = []
        self.reject(project, 'Integer stepper tags require a whole-number step')
        control['step'] = 1
        saved = self.client.put('/api/project/draft', json={
            'expected_revision': self.state['draft_revision'], 'project': project})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()['active_revision'], self.state['active_revision'])

    def test_each_control_is_fully_checked_before_the_next_control(self):
        project = copy.deepcopy(self.state['draft'])
        project['controls'] = [
            {'id': 'first', 'kind': 'numeric', 'label': 'First', 'tag': 'MissingTag'},
            {'id': 'second', 'kind': 'stepper', 'label': 'Second', 'tag': 'RuleRequest',
             'minimum_tag': 'MotorRunning'},
        ]
        self.reject(project, 'Unknown or incompatible tag: MissingTag')
        project['controls'][0]['tag'] = 'TankLevel'
        self.reject(project, 'Edit limits require an existing numeric tag')

    def test_project_rules_precede_control_and_history_rules(self):
        project = copy.deepcopy(self.state['draft'])
        project['controls'][0]['tag'] = 'MissingTag'
        project['alarms'][0]['related_screen'] = 'missing_screen'
        self.reject(project, 'Alarm navigation requires an existing non-popup screen')
        project['alarms'][0]['related_screen'] = ''
        self.reject(project, 'Unknown or incompatible tag: MissingTag')
        project['controls'] = [{'id': 'unit', 'kind': 'faceplate', 'label': 'Unit',
                                'template': 'unit', 'root_tag': 'MissingRoot'}]
        project['faceplates'] = [{'id': 'unit', 'name': 'Unit', 'controls': []}]
        project['historian']['tags'] = [{'tag': 'MissingHistory', 'sample_ms': 1000, 'deadband': 0}]
        self.reject(project, 'Faceplate requires a compatible UDT tag and definition')
        project['controls'] = []
        self.reject(project, 'History requires an existing numeric or Boolean tag')


if __name__ == '__main__':
    unittest.main()
