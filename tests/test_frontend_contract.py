"""Cross-language contract tests against the actual Puck config and serializers.

Requires Node and npm ci, as does the frontend asset build. No browser, server,
network PLC connection or generated schema snapshot is used.
"""
import copy
import json
from pathlib import Path
import subprocess
import unittest

from pydantic import TypeAdapter, ValidationError
from openhmi.project_models import Control, Project, SaveRequest, ApplyRequest
from openhmi.screens import expanded_controls
from openhmi.control_contracts import ButtonRequest, ValueRequest, EDIT_INPUTS
from openhmi.acquisition_routes import SubscriptionRequest
from openhmi.alarm_contracts import AcknowledgeRequest, SelectedAcknowledgement
from openhmi.trend_contracts import CaptureCommand
from openhmi.identity_contracts import StationClaim
from urllib.parse import parse_qs, urlsplit, unquote


ROOT = Path(__file__).resolve().parents[1]
CONTROL = TypeAdapter(Control)


def frontend(operation, **payload):
    result = subprocess.run(
        ['node', 'tests/frontend_contract.mjs'], cwd=ROOT,
        input=json.dumps({'operation': operation, **payload}),
        encoding='utf-8', capture_output=True, timeout=60, check=False,
    )
    if result.returncode:
        raise AssertionError(f'Frontend contract process failed:\n{result.stderr}')
    return json.loads(result.stdout)


def palette_defaults():
    # Mode feedback deliberately starts unbound in the real palette. Supply
    # that operator-required binding without replacing any default values.
    return frontend('defaults', bindings={'ModeSelector': {'confirmed_tag': 'ModeFeedback'}}, catalog={
        'security_groups': ['Operators'],
        'actions': [{'name': 'toggle_motor', 'label': 'Toggle motor'}],
        'tags': [
            {'name': 'TankLevel', 'type': 'number', 'writable': True},
            {'name': 'RecipeRevision', 'type': 'number', 'writable': False},
            {'name': 'AlarmWord', 'type': 'number', 'integer': True, 'unscaled': True, 'writable': True},
            {'name': 'ModeFeedback', 'type': 'number', 'integer': True, 'unscaled': True, 'writable': False},
            {'name': 'MotorRunning', 'type': 'boolean', 'writable': True},
            {'name': 'ProcessAlarm', 'type': 'boolean', 'writable': False},
            {'name': 'OperatorText', 'type': 'string', 'writable': True},
            {'name': 'Motor', 'type': 'struct', 'writable': True},
        ],
        'connections': [], 'commands': [], 'screens': [],
        'faceplates': [{'id': 'motor', 'name': 'Motor', 'members': {}}],
    })


class FrontendContractTests(unittest.TestCase):
    def test_recipe_component_exports_and_palette_preserve_function_identity(self):
        self.assertEqual(frontend('recipe_component_exports', catalog={'tags': [], 'actions': [], 'security_groups': []}),
                         dict(picture=True, loaded=True, selected=True, palette=True))

    @classmethod
    def setUpClass(cls):
        cls.defaults = palette_defaults()

    def test_palette_and_backend_control_kinds_match(self):
        schema = CONTROL.json_schema()
        self.assertEqual(set(schema['discriminator']['mapping']), set(self.defaults['types']))
        self.assertEqual(set(self.defaults['types'].values()), set(self.defaults['components']))
        self.assertEqual(len(self.defaults['types']), len(set(self.defaults['types'].values())))

    def test_palette_families_and_categories_cover_each_component_once(self):
        for label in ('families', 'categories'):
            names = [name for group in self.defaults[label] for name in group]
            with self.subTest(registry=label):
                self.assertEqual(len(names), len(set(names)))
                self.assertEqual(set(names), set(self.defaults['components']))

    def test_palette_defaults_with_required_bindings_validate_as_a_project(self):
        project = Project.model_validate(self.defaults['project'])
        self.assertEqual(len(project.controls), len(self.defaults['types']))

    def test_input_palette_kinds_are_routed_as_edits(self):
        kinds = {kind for kind, component in self.defaults['types'].items()
                 if component in self.defaults['inputTypes']}
        # The mode selector also submits audited values, but lives with machine
        # controls because it displays separate PLC confirmation feedback.
        self.assertEqual(kinds | {'mode_selector'}, set(EDIT_INPUTS))

    def test_palette_select_options_are_accepted_by_backend_models(self):
        # Empty binding sentinels are incomplete forms, not saved configurations.
        # Test every nonempty production select option, including enum choices.
        self.assertTrue(self.defaults['selections'])
        for selection in self.defaults['selections']:
            with self.subTest(component=selection['component'], field=selection['field'], value=selection['value']):
                CONTROL.validate_python(selection['control'])

    def test_browser_request_payloads_match_router_models(self):
        requests = frontend('requests')
        self.assertEqual(len(requests), 9)
        values = [0, 0.25, False, True, '001 设备', '']
        for request, value in zip(requests[:6], values, strict=True):
            with self.subTest(value=value):
                self.assertEqual(request['path'], '/api/controls/details__motor__speed/value')
                self.assertEqual(request['method'], 'PUT')
                body = ValueRequest.model_validate_json(json.dumps(request['body']))
                self.assertEqual(body.value, value)
                self.assertIs(type(body.value), type(value))
                self.assertEqual(body.expected_revision, 123)
        self.assertEqual(requests[6]['path'], '/api/controls/details__motor__start/activate')
        self.assertEqual(requests[6]['method'], 'POST')
        self.assertEqual(ButtonRequest.model_validate(requests[6]['body']).expected_revision, 123)
        for request, sequence in zip(requests[7:], [42, 43], strict=True):
            self.assertEqual(request['path'], '/api/subscriptions')
            self.assertEqual(request['method'], 'POST')
            self.assertEqual(SubscriptionRequest.model_validate(request['body']).sequence, sequence)
        self.assertEqual(requests[7]['body']['screens'], ['overview', 'details'])
        self.assertEqual(requests[7]['body']['preview_root'], 'MotorA')
        self.assertEqual(requests[8]['body']['screens'], [])
        self.assertTrue(requests[8]['keepalive'])
        for request in requests:
            self.assertEqual(request['headers']['X-OpenHMI-Project'], 'a' * 32)
            self.assertEqual(request['headers']['Content-Type'], 'application/json')

    def test_capture_station_and_image_requests_match_service_contracts(self):
        requests = frontend('service_requests')
        self.assertEqual(len(requests), 8)
        for request, action, capture in zip(requests[:3], ['start', 'stop', 'delete'], [0, 123, 123], strict=True):
            self.assertEqual(unquote(request['path']), '/api/trends/设备 / trend?#')
            self.assertNotIn('?', request['path'])
            self.assertEqual(request['method'], 'POST')
            body = CaptureCommand.model_validate(request['body'])
            self.assertEqual((body.action, body.capture_id), (action, capture))
        self.assertEqual(requests[3]['path'], '/api/security/publication')
        self.assertNotIn('body', requests[3])
        for request, suffix in zip(requests[4:7], ['claim', 'claim?renew=true', 'release'], strict=True):
            self.assertEqual(request['path'], '/api/security/publication/' + suffix)
            self.assertEqual(request['method'], 'POST')
            self.assertEqual(StationClaim.model_validate(request['body']).client, 'station 设备')
        self.assertEqual(parse_qs(urlsplit(requests[5]['path']).query), {'renew': ['true']})
        image = requests[7]
        self.assertEqual(urlsplit(image['path']).path, '/api/canvas-images')
        self.assertEqual(parse_qs(urlsplit(image['path']).query), {'name': ['机器 pic #.png']})
        self.assertEqual(image['method'], 'POST')
        self.assertEqual(image['upload'], {'name': '机器 pic #.png', 'type': 'image/png', 'bytes': [137, 80, 78, 71]})
        self.assertTrue(image['timeout'])
        self.assertNotIn('Content-Type', image['headers'])
        for request in requests:
            self.assertEqual(request['headers']['X-OpenHMI-Project'], 'a' * 32)
        for request in [*requests[:3], *requests[4:7]]:
            self.assertEqual(request['headers']['Content-Type'], 'application/json')

    def test_capture_and_station_contracts_reject_invalid_payloads(self):
        for body in ({'action': 'restart'}, {'action': 'start', 'capture_id': True},
                     {'action': 'stop', 'capture_id': -1}, {'action': 'delete', 'capture_id': 2**63},
                     {'action': 'start', 'extra': 1}):
            with self.subTest(body=body), self.assertRaises(ValidationError):
                CaptureCommand.model_validate(body)
        for body in ({'client': ''}, {'client': 'x' * 101}, {'client': 123}, {'client': 'station', 'extra': True}):
            with self.subTest(body=body), self.assertRaises(ValidationError):
                StationClaim.model_validate(body)

    def test_project_and_alarm_payloads_match_lifecycle_models(self):
        project = Project.model_validate(self.defaults['project']).model_dump(mode='json')
        requests = frontend('lifecycle_requests', project=project)
        self.assertEqual([request['path'] for request in requests], [
            '/api/project/draft', '/api/project/apply', '/api/project/apply',
            '/api/alarms/1/acknowledge', '/api/alarms/acknowledge-all', '/api/alarms/acknowledge-selected',
        ])
        self.assertEqual([request['method'] for request in requests], ['PUT', *['POST'] * 5])
        save = SaveRequest.model_validate_json(json.dumps(requests[0]['body']))
        self.assertEqual(save.expected_revision, 123)
        self.assertEqual(save.project.model_dump(mode='json'), project)
        apply = ApplyRequest.model_validate(requests[1]['body'])
        self.assertEqual((apply.expected_revision, apply.reason), (123, '更改画面'))
        self.assertEqual(ApplyRequest.model_validate(requests[2]['body']).reason, 'Live apply')
        self.assertEqual(AcknowledgeRequest.model_validate(requests[3]['body']).comment, '已检查')
        self.assertEqual(AcknowledgeRequest.model_validate(requests[4]['body']).comment, 'All inspected')
        selected = SelectedAcknowledgement.model_validate(requests[5]['body'])
        self.assertEqual(selected.occurrence_ids, [2, 3])
        self.assertEqual(selected.comment, 'Selected inspected')
        for request in requests:
            self.assertEqual(request['headers']['X-OpenHMI-Project'], 'a' * 32)

    def test_catalog_rebuilds_keep_options_fresh_and_match_tag_types(self):
        catalogs = [
            {'security_groups': ['Operators'], 'actions': [], 'tags': [
                {'name': 'IntegerGood', 'type': 'number', 'integer': True, 'unscaled': True, 'writable': True},
                {'name': 'IntegerScaled', 'type': 'number', 'integer': True, 'unscaled': False, 'writable': True},
                {'name': 'FloatGood', 'type': 'number', 'writable': True},
                {'name': 'ReadOnly', 'type': 'number', 'writable': False},
            ]},
            {'security_groups': ['Engineers'], 'actions': [], 'tags': [
                {'name': 'NewReadOnly', 'type': 'number', 'writable': False},
                {'name': 'TextGood', 'type': 'string', 'writable': True},
                {'name': 'TextReadOnly', 'type': 'string', 'writable': False},
            ]},
            {'security_groups': [], 'actions': [], 'tags': []},
        ]
        first, second, empty = frontend('catalogs', catalogs=catalogs)
        self.assertEqual([option['value'] for option in first['sliderTags']], ['', 'IntegerGood', 'FloatGood'])
        self.assertEqual([option['value'] for option in first['modeTags']], ['', 'IntegerGood'])
        self.assertEqual([option['value'] for option in second['numericTags']], ['NewReadOnly'])
        self.assertEqual(second['slider']['tag'], '')
        self.assertEqual(second['sliderTags'], [{'label': 'Choose a writable numeric tag', 'value': ''}])
        self.assertEqual(empty['numericTags'], [])
        self.assertEqual(empty['dropdown']['tag'], '')
        for config in (first, second, empty):
            self.assertEqual(config['states'][0]['label'], 'Stopped')
            self.assertNotIn('Poison', [option['value'] for option in config['numericTags']])
        for config, expected_type in ((first, int), (second, str)):
            dropdown = CONTROL.validate_python({'kind': 'dropdown', 'id': 'choice', **config['dropdown']})
            self.assertTrue(all(type(option.value) is expected_type for option in dropdown.options))

    def test_faceplate_bindings_match_backend_on_overview_and_secondary_screens(self):
        project = Project.model_validate(self.defaults['project']).model_dump(mode='json')
        members = [control for control in project['controls'] if control['kind'] != 'faceplate']
        tag_fields = ('tag', 'target', 'visible_tag', 'enabled_tag', 'color_tag', 'minimum_tag',
                      'maximum_tag', 'min_length_tag', 'max_length_tag', 'address_tag',
                      'refresh_tag', 'confirmed_tag', 'setpoint_tag', 'tolerance_tag')
        for control in members:
            for field in tag_fields:
                if field in control:
                    control[field] = '$.' + field
            for field in ('checks', 'lamps'):
                for row in control.get(field, []):
                    row['tag'] = '$.Nested.Signal'
            if isinstance(control.get('series'), list):
                for index, row in enumerate(control['series']):
                    for field in ('tag', 'x_tag', 'y_tag'):
                        if field in row:
                            row[field] = f'$.Nested.Axis{index}.' + field
            if control['kind'] == 'trend':
                control.update(tags=['$.Speed', 'GlobalValue'],
                               series={'$.Speed': {'decimals': 3, 'minimum': -10, 'maximum': 100}},
                               recording={'sample_ms': 500, 'max_samples': 500,
                                          'start_tag': '$.StartCapture', 'stop_tag': 'GlobalStop'})
        instance = {'id': 'motor', 'kind': 'faceplate', 'label': 'Motor', 'template': 'motor',
                    'root_tag': 'Machine.Motors[2]', 'visible_tag': 'ShowMotor', 'enabled_tag': 'PermitMotor'}
        project.update(controls=[instance], faceplates=[{'id': 'motor', 'name': 'Motor', 'controls': members}],
                       screens=[{'id': 'details', 'title': 'Details', 'controls': [copy.deepcopy(instance)]}])
        project = Project.model_validate(project).model_dump(mode='json')
        original = copy.deepcopy(project)
        for screen in ('overview', 'details'):
            actual = frontend('faceplates', project=project, screen=screen)
            expected = expanded_controls(project, screen)
            for browser, backend in zip(actual, expected, strict=True):
                with self.subTest(screen=screen, kind=backend['kind']):
                    self.assertEqual(browser.pop('instance_enabled_tag'), backend.pop('_parent_enabled'))
                    backend.pop('_parent_visible')
                    backend.pop('_screen')
                    if browser['kind'] == 'trend':
                        pens = browser.pop('pens')
                        self.assertEqual(pens['tags'], backend['tags'])
                        self.assertEqual(pens['series'], backend['series'])
                        self.assertEqual(pens['root'], instance['root_tag'])
                    self.assertEqual(browser, backend)
        self.assertEqual(project, original)

    def test_all_control_fields_survive_backend_frontend_roundtrip(self):
        project = Project.model_validate(self.defaults['project']).model_dump(mode='json')
        for control in project['controls']:
            control.update(label='设备 Δ ' + control['kind'], visible_tag='Visible',
                           enabled_tag='Enabled', color_tag='Highlight', active_color='#333333')
            if 'security_groups' in control:
                control['security_groups'] = ['Operators']
            if 'minimum_tag' in control:
                control.update(minimum_tag='LowLimit', maximum_tag='HighLimit')
            if 'max_length_tag' in control:
                control.update(min_length_tag='MinLength', max_length_tag='MaxLength')
            for field in ('image', 'on_image', 'off_image'):
                if field in control:
                    control[field] = 'a' * 64
            for state in control.get('states', []):
                if 'image' in state:
                    state['image'] = 'b' * 64
        # Include values that differ from defaults and have caused model drift.
        overrides = {
            'stepper': {'step': 0.25, 'decimals': 2},
            'image': {'fit': 'cover', 'show_label': False, 'alt_text': '机器背景'},
            'position_image': {'direction': 'right_to_left', 'size_percent': 25, 'show_label': False},
            'rotation_image': {'angle_start': 90, 'angle_end': -90, 'show_label': False},
            'tag_quality': {'show_age': False},
            'mode_selector': {'presentation': 'segments'},
            'duration': {'source_unit': 'seconds', 'decimals': 3},
            'dropdown': {'options': [{'value': '001', 'label': '一'}, {'value': '002', 'label': '二'}]},
            'button': {'mode': 'set', 'target': 'Request', 'value': '001'},
            'trend': {'series': {'TankLevel': {'decimals': 3, 'minimum': -10, 'maximum': 120}},
                      'recording': {'sample_ms': 500, 'max_samples': 1234,
                                    'start_tag': 'StartCapture', 'stop_tag': 'StopCapture'}},
        }
        for control in project['controls']:
            control.update(overrides.get(control['kind'], {}))
            CONTROL.validate_python(control)
        # Secondary screens and project settings must survive editing Overview.
        project['screens'] = [{'id': 'secondary', 'title': 'Secondary', 'columns': 1,
                               'update_ms': 1000, 'popup': True, 'layout': None,
                               'controls': [copy.deepcopy(project['controls'][0])]}]
        project['faceplates'] = [{'id': 'motor', 'name': 'Motor', 'udt_type': 'MotorUDT',
                                  'members': {'Speed': 'number'},
                                  'controls': [{'kind': 'numeric', 'id': 'speed',
                                                'label': 'Speed', 'tag': '$.Speed'}]}]
        expected = Project.model_validate(project).model_dump(mode='json')
        actual = frontend('roundtrip', projects=[expected])[0]
        for before, after in zip(expected['controls'], actual['controls'], strict=True):
            with self.subTest(kind=before['kind']):
                # Do not let backend defaults conceal a dropped serialized field.
                self.assertEqual(set(before), set(after), f"Fields lost for {before['kind']}")
                self.assertEqual(before, after)
        self.assertEqual(Project.model_validate(actual).model_dump(mode='json'), expected)


if __name__ == '__main__':
    unittest.main()
