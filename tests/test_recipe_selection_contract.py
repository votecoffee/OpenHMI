"""SQL-loaded recipe copies checked by the actual browser selection validator."""
from copy import deepcopy
from io import BytesIO
from threading import RLock
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError
from openhmi.projects import ProjectStore
from openhmi.recipe_auth import RecipeUser
from openhmi.recipe_models import RecipeContent, RecipeCreate, RecipeParameter, RecipeSelect
from openhmi.recipe_routes import add_recipe_routes
from openhmi.recipes import RecipeService
from tests.test_frontend_contract import frontend


def content(image_id=None):
    values = [('zero', 'number', 0.0), ('fraction', 'number', 12.125), ('large', 'number', 1e100),
              ('low', 'integer', -(2**53 - 1)), ('high', 'integer', 2**53 - 1),
              ('enabled', 'boolean', False), ('code', 'text', '001,设备\nΔ')]
    return {'title': '设备 Recipe Δ', 'description': 'Offline fixture', 'image_id': image_id,
            'parameters': [dict(name=name, label=name, type=kind, value=value, unit='')
                           for name, kind, value in values]}


class RecipeSelectionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = frontend('recipe_selections', selections=[])['path']

    def fixture(self):
        store = ProjectStore()
        self.addCleanup(store.close)
        # Receipt publication is stubbed: no simulator, PLC reads or transport.
        driver = Mock(spec=['load_recipe', 'read'])
        driver.read.side_effect = AssertionError('Selection fixtures cannot read controller tags')
        application = SimpleNamespace(lock=RLock(), driver=driver)
        user = RecipeUser('Fixture Engineer Δ', frozenset({'engineer', 'approver', 'operator', 'administrator'}))
        security = SimpleNamespace(configured=lambda: True, user=Mock(return_value=user))
        app = FastAPI()
        add_recipe_routes(app, store, application, security=security, commands=SimpleNamespace())
        return store, application, user, TestClient(app)

    def test_actual_sql_selection_lifecycle_image_and_independent_loaded_copy(self):
        store, application, user, client = self.fixture()
        selections = []
        def selected():
            response = client.get(self.path)
            self.assertEqual(response.status_code, 200, response.text)
            selections.append(response.json())
            return selections[-1]
        def post(path, body):
            response = client.post(path, json={**body, 'reason': 'Offline contract fixture'})
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()
        def load(revision=None):
            result = post('/api/recipes/select', {'expected_selection_version': selected()['version'],
                'revision_id': revision['id'] if revision else None,
                'expected_revision_version': revision['version'] if revision else None})
            self.assertEqual(selected(), result)
            return result
        def transition(revision, action):
            return post(f"/api/recipe-revisions/{revision['id']}/transition",
                        {'expected_version': revision['version'], 'action': action})
        with client:
            self.assertEqual(selected(), {'version': 1, 'snapshot': None})
            image = BytesIO()
            Image.new('RGB', (2, 2), '#123456').save(image, format='PNG')
            uploaded = client.post('/api/recipe-images?reason=Offline%20image', content=image.getvalue(),
                                   headers={'content-type': 'image/png'})
            self.assertEqual(uploaded.status_code, 200, uploaded.text)
            payload = RecipeContent.model_validate(content(uploaded.json()['image_id'])).model_dump()
            revision = post('/api/recipes', {'code': 'FIXTURE', 'content': payload})
            test_copy = load(revision)
            self.assertFalse(test_copy['snapshot']['production_approved'])
            self.assertIsNone(test_copy['snapshot']['approved_by'])
            approved = transition(transition(revision, 'submit'), 'approve')
            self.assertEqual(selected(), test_copy)
            production = load(approved)
            self.assertTrue(production['snapshot']['production_approved'])
            self.assertEqual(production['snapshot']['approved_by'], user.name)
            self.assertEqual(production['snapshot']['loaded_by'], user.name)
            self.assertEqual(production['snapshot']['content'], payload)
            reopened = RecipeService(store, application)
            self.assertEqual(reopened.selected(), production)
            selections.append(reopened.selected())
            changed = deepcopy(payload)
            changed['parameters'][-1]['value'] = '002,设备'
            newer = post(f"/api/recipes/{revision['recipe_id']}/revisions", {
                'expected_latest_revision': approved['id'], 'parent_revision': approved['id'], 'content': changed})
            transition(approved, 'withdraw')
            self.assertEqual(selected(), production)
            self.assertFalse(load(newer)['snapshot']['production_approved'])
            cleared = load()
            self.assertIsNone(cleared['snapshot'])
            reopened = RecipeService(store, application)
            self.assertEqual(reopened.selected(), cleared)
            selections.append(reopened.selected())
        result = frontend('recipe_selections', selections=selections)
        self.assertEqual(result['path'], '/api/recipes/selected')
        self.assertEqual(result['valid'], [True] * len(selections))
        application.driver.read.assert_not_called()
        self.assertEqual({call[0] for call in application.driver.mock_calls}, {'load_recipe'})

    def test_malformed_selection_and_typed_parameter_boundaries(self):
        _, application, user, _ = self.fixture()
        service = application.recipes
        revision = service.create(RecipeCreate(code='BASE', content=content(), reason='Offline fixture'), user)
        selection = service.select(RecipeSelect(revision_id=revision['id'], expected_revision_version=revision['version'],
                                               expected_selection_version=1, reason='Offline fixture'), user)
        valid = [selection, {'version': 1, 'snapshot': None},
                 {**deepcopy(selection), 'snapshot': {**deepcopy(selection['snapshot']), 'content': {
                     **deepcopy(selection['snapshot']['content']), 'parameters': []}}}]
        invalid = [None, [], {}, {**selection, 'version': 0}, {**selection, 'version': True},
                   {**selection, 'snapshot': {}}, {**selection, 'snapshot': False}]
        for key, value in (('number', 0), ('number', 2**53), ('code', None), ('loaded_by', {}),
                           ('loaded_at', None), ('production_approved', 'false'), ('approved_by', {})):
            invalid.append({**deepcopy(selection), 'snapshot': {**deepcopy(selection['snapshot']), key: value}})
        for changes in ({'image_id': 'not-an-image-id'}, {'title': None}, {'parameters': [None]}, {'parameters': None}):
            item = deepcopy(selection)
            item['snapshot']['content'].update(changes)
            invalid.append(item)
        for kind, value in (('integer', 2**53), ('integer', True), ('number', '12.5'), ('boolean', 1), ('text', 12)):
            parameter = dict(name='bad', label='Bad', unit='', type=kind, value=value)
            with self.assertRaises(ValidationError): RecipeParameter.model_validate(parameter)
            item = deepcopy(selection)
            item['snapshot']['content']['parameters'] = [parameter]
            invalid.append(item)
        for parameter in selection['snapshot']['content']['parameters']:
            RecipeParameter.model_validate(parameter)
        self.assertEqual(frontend('recipe_selections', selections=valid + invalid)['valid'],
                         [True] * len(valid) + [False] * len(invalid))
        application.driver.read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
