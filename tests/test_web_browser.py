"""Offline schema, project apply and PLC demand coverage for camera controls."""

import unittest

from fastapi.testclient import TestClient
from pydantic import ValidationError

from openhmi.logix import RuntimeDriver
from openhmi.projects import Project, WebBrowserControl
from openhmi.screens import expanded_controls, referenced_tags
from openhmi.server import create_app
from tests.test_logix_history import FakePLC, logix_project


def camera(**settings):
    return {'id': 'view', 'label': 'Camera view', 'kind': 'web_browser',
            'hosts': 'camera-a.invalid, 192.0.2.10', 'path': '/view', **settings}


class WebBrowserTests(unittest.TestCase):
    def test_endpoint_policy_rejects_ambiguous_hosts_and_paths(self):
        for settings in (
            {'scheme': 'file'}, {'hosts': 'user@camera.invalid'}, {'hosts': '*.invalid'},
            {'hosts': '127.1'}, {'hosts': '0x7f000001'}, {'hosts': 'camera-a.invalid, CAMERA-A.INVALID'},
            {'hosts': 'camera-a.invalid:443'}, {'hosts': 'camera-a.invalid; frame-src *'},
            {'path': '/view?token=x'}, {'path': '/%2e%2e/view'}, {'path': '/view/../admin'},
            {'path': '//camera.invalid/view'}, {'port': 0},
        ):
            with self.subTest(settings=settings), self.assertRaises(ValidationError):
                WebBrowserControl.model_validate(camera(**settings))

    def test_save_and_apply_check_camera_bindings(self):
        app = create_app()
        self.addCleanup(app.state.store.close)
        self.addCleanup(app.state.driver.close)
        client = TestClient(app)
        state = client.get('/api/project').json()
        project = state['active']
        project['tags'].append({'name': 'CameraSequence', 'type': 'integer', 'initial': 0})
        cases = [
            (camera(hosts=''), None),
            (camera(address_tag='MotorRunning'), 'STRING tag'),
            (camera(refresh_tag='TankLevel'), 'BOOL or integer tag'),
            (camera(address_tag='OperatorText', refresh_tag='CameraSequence'), None),
        ]
        for control, error in cases:
            with self.subTest(control=control):
                project['controls'] = [control]
                draft = client.put('/api/project/draft', json={'project': project, 'expected_revision': state['draft_revision']})
                if error:
                    self.assertEqual(draft.status_code, 422, draft.text)
                    self.assertIn(error, draft.json()['detail'])
                else:
                    self.assertEqual(draft.status_code, 200, draft.text)
                    state = draft.json()
                    response = client.post('/api/project/apply', json={'expected_revision': state['draft_revision']})
                    self.assertEqual(response.status_code, 200, response.text)

    def test_faceplate_camera_bindings_join_read_only_screen_demand(self):
        project = logix_project()
        project['tags'][0]['members']['Address'] = 'string'
        project['faceplates'] = [{
            'id': 'camera', 'name': 'Camera faceplate', 'udt_type': 'MotorUDT',
            'members': {'Address': 'string', 'Running': 'boolean'},
            'controls': [camera(address_tag='$.Address', refresh_tag='$.Running')],
        }]
        project['screens'][0]['controls'] = [{
            'id': 'equipment', 'label': 'Equipment', 'kind': 'faceplate', 'template': 'camera', 'root_tag': 'MotorA',
        }]
        project['alarms'] = []
        project = Project.model_validate(project).model_dump()
        control, = expanded_controls(project, 'fast')
        self.assertEqual(referenced_tags(control), {'MotorA.Address', 'MotorA.Running'})

        class CameraPLC(FakePLC):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.values['Motor']['Address'] = 'camera-a.invalid'

        driver = RuntimeDriver(CameraPLC)
        self.addCleanup(driver.close)
        driver.configure(project)
        driver.lease('camera-viewer', ['fast'], 1)
        self.assertEqual(driver.demands(1), {'MotorA.Address': 100, 'MotorA.Running': 100})
        driver.poll(1)
        plc = driver.connections['plc'].client
        self.assertEqual(plc.reads, [('Motor',)])
        self.assertEqual(plc.writes, [])
        self.assertEqual(driver.sample_snapshot(1)['MotorA.Address']['value'], 'camera-a.invalid')
