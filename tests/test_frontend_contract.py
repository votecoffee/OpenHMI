"""Cross-language contract tests against the actual Puck config and serializers.

Requires Node and npm ci, as does the frontend asset build. No browser, server,
network PLC connection or generated schema snapshot is used.
"""
import copy
import json
from pathlib import Path
import subprocess
import unittest

from pydantic import TypeAdapter
from openhmi.projects import Control, Project


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


class FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Mode feedback deliberately starts unbound in the real palette. Supply
        # that operator-required binding without replacing any default values.
        cls.defaults = frontend('defaults', bindings={'ModeSelector': {'confirmed_tag': 'ModeFeedback'}}, catalog={
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

    def test_palette_and_backend_control_kinds_match(self):
        schema = CONTROL.json_schema()
        self.assertEqual(set(schema['discriminator']['mapping']), set(self.defaults['types']))
        self.assertEqual(set(self.defaults['types'].values()), set(self.defaults['components']))
        self.assertEqual(len(self.defaults['types']), len(set(self.defaults['types'].values())))

    def test_palette_defaults_with_required_bindings_validate_as_a_project(self):
        project = Project.model_validate(self.defaults['project'])
        self.assertEqual(len(project.controls), len(self.defaults['types']))

    def test_palette_select_options_are_accepted_by_backend_models(self):
        # Empty binding sentinels are incomplete forms, not saved configurations.
        # Test every nonempty production select option, including enum choices.
        self.assertTrue(self.defaults['selections'])
        for selection in self.defaults['selections']:
            with self.subTest(component=selection['component'], field=selection['field'], value=selection['value']):
                CONTROL.validate_python(selection['control'])

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
