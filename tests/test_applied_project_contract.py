"""Actual saved-project responses checked by the production live-layout guard."""
from copy import deepcopy
import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openhmi.project_lifecycle_routes import add_project_lifecycle_routes
from openhmi.project_models import Project, SaveRequest, RevisionRequest
from openhmi.projects import ProjectStore
from tests.test_frontend_contract import frontend, palette_defaults


class AppliedProjectContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.palette = palette_defaults()
        cls.path = frontend('applied_projects', snapshots=[])['path']

    def fixture(self):
        store = ProjectStore()
        self.addCleanup(store.close)
        dependencies = {name: Mock(name=name) for name in ('application', 'security', 'commands', 'monitor',
                        'trends', 'historian', 'publisher', 'validate_bindings', 'sample_alarms')}
        app = FastAPI()
        add_project_lifecycle_routes(app, store, **dependencies, instance='a' * 32)
        return store, dependencies, TestClient(app)

    def candidate(self):
        project = deepcopy(self.palette['project'])
        ids = [item['id'] for item in project['controls']]
        project.update(title='机器 overview Δ', columns=3, update_ms=100,
            screens=[{'id': 'details', 'title': 'Details Δ', 'columns': 1, 'update_ms': 60000, 'popup': True,
                      'controls': [{**deepcopy(project['controls'][0]), 'id': 'detail_value'}]}],
            faceplates=[{'id': 'motor', 'name': 'Motor', 'udt_type': 'FixtureUDT', 'members': {'Speed': 'number'},
                         'controls': [{'id': 'speed', 'kind': 'numeric', 'label': '速度', 'tag': '$.Speed'}]}],
            layout={'width': 1920, 'height': 1080, 'snap': False,
                'boxes': {identifier: {'x': index % 8 * 160, 'y': index // 8 * 80,
                         'width': 144, 'height': 64, 'z': index, 'group': 'pair' if index < 2 else ''}
                         for index, identifier in enumerate(ids)},
                'containers': {'panel': {'x': 0, 'y': 0, 'width': 600, 'height': 180,
                                        'mode': 'grid', 'columns': 2, 'members': ids[:2]},
                               'stack': {'x': 640, 'y': 0, 'width': 300, 'height': 300,
                                         'mode': 'stack', 'members': ids[2:4]}},
                'decorations': {'machine': {'x': 0, 'y': 0, 'width': 1280, 'height': 720,
                                            'kind': 'rectangle', 'label': '机器', 'locked': True}}})
        return Project.model_validate(project)

    def test_real_active_responses_keep_applied_revision_palette_and_layout(self):
        store, dependencies, client = self.fixture()
        snapshots = []
        def capture():
            response = client.get(self.path)
            self.assertEqual(response.status_code, 200, response.text)
            snapshots.append(response.json())
            return snapshots[-1]
        def save(project):
            return store.save(SaveRequest(expected_revision=store.snapshot()['draft_revision'], project=project))
        with client:
            original = capture()
            candidate = self.candidate()
            saved = save(candidate)
            self.assertEqual(capture(), original, 'An unapplied draft cannot replace the live layout')
            store.apply(RevisionRequest(expected_revision=saved['draft_revision']))
            active = capture()
            self.assertEqual(active['revision'], saved['draft_revision'])
            self.assertEqual(active['project'], candidate.model_dump(mode='json'))
            self.assertEqual({item['kind'] for item in active['project']['controls']}, set(self.palette['types']))
            self.assertTrue(active['project']['layout']['decorations']['machine']['locked'])
            self.assertEqual(active['project']['faceplates'][0]['controls'][0]['tag'], '$.Speed')
            flow = candidate.model_copy(deep=True)
            flow.layout = None
            flow.title = 'Flow layout after apply'
            saved = save(flow)
            self.assertEqual(capture(), active)
            store.apply(RevisionRequest(expected_revision=saved['draft_revision']))
            self.assertIsNone(capture()['project']['layout'])
        result = frontend('applied_projects', snapshots=snapshots)
        self.assertEqual(result['path'], '/api/project/active')
        self.assertEqual(result['valid'], [True] * len(snapshots))
        # Read projections and direct store fixtures never apply to a runtime/PLC.
        for service in dependencies.values(): self.assertEqual(service.mock_calls, [])

    def test_legacy_defaults_and_malformed_consumed_shapes(self):
        store, _, client = self.fixture()
        candidate = self.candidate()
        saved = store.save(SaveRequest(expected_revision=1, project=candidate))
        store.apply(RevisionRequest(expected_revision=saved['draft_revision']))
        with client:
            current = client.get(self.path).json()
        legacy = deepcopy(current)
        for key in ('columns', 'update_ms', 'layout', 'screens', 'faceplates', 'connections', 'tags', 'commands',
                    'recipe_transfers', 'languages', 'alarms'):
            legacy['project'].pop(key, None)
        valid = [current, legacy]
        invalid = [None, [], {}, *[{**deepcopy(current), key: value} for key, value in (
            ('revision', 0), ('revision', True), ('revision', 2**53), ('project_instance', 'wrong'),
            ('project_instance', 'A' * 32), ('project', None))]]
        for changes in ({'controls': [None]}, {'controls': [{'id': 'bad', 'label': 'Bad', 'kind': 'unknown'}]},
                        {'columns': 4}, {'update_ms': 99}, {'update_ms': 60001}, {'screens': [None]},
                        {'screens': [{**current['project']['screens'][0], 'id': None}]},
                        {'faceplates': [{'controls': None}]},
                        *[{key: {}} for key in ('connections', 'tags', 'commands', 'recipe_transfers', 'languages', 'alarms')]):
            item = deepcopy(current)
            item['project'].update(changes)
            invalid.append(item)
        for changes in ({'boxes': []}, {'boxes': {'bad': None}}, {'containers': []},
                        {'containers': {'bad': {'members': None}}}, {'decorations': []},
                        {'decorations': {'bad': None}}):
            item = deepcopy(current)
            item['project']['layout'].update(changes)
            invalid.append(item)
        self.assertEqual(frontend('applied_projects', snapshots=valid + invalid)['valid'],
                         [True] * len(valid) + [False] * len(invalid))


if __name__ == '__main__':
    unittest.main()
