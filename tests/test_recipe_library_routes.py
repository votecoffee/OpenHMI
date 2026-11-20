"""Recipe library adapters without SQL, image processing or driver construction."""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from openhmi.recipe_auth import RecipeUser
from openhmi.recipe_library_routes import add_recipe_library_read_routes, add_recipe_library_mutation_routes
from openhmi.recipe_models import RecipeCreate, RecipeSave, RecipeTransition, RecipeSelect, PolicyChange, SimulationPermit


class RecipeLibraryRouteTests(unittest.TestCase):
    def fixture(self):
        service = SimpleNamespace(**{name: Mock(return_value={'result': name}) for name in
                                    ('snapshot', 'selected', 'create', 'save', 'transition', 'select', 'update_policy', 'simulator_permit')})
        user = Mock(return_value=RecipeUser('Fixture Engineer', frozenset({'engineer'})))
        invoke = Mock(side_effect=lambda method, *args: method(*args))
        app = FastAPI()
        add_recipe_library_read_routes(app, service)
        add_recipe_library_mutation_routes(app, service, user, invoke)
        client = TestClient(app)
        self.addCleanup(client.close)
        return app, client, service, user, invoke

    def cases(self):
        content = {'title': '设备 Δ', 'parameters': [{'name': 'serial', 'label': 'Serial', 'type': 'text', 'value': '001,+%'}]}
        reason = {'reason': ' Review Δ '}
        return [
            ('POST', '/api/recipes', 'create', RecipeCreate, {**reason, 'code': 'A', 'content': content}, ()),
            ('POST', '/api/recipes/7/revisions', 'save', RecipeSave,
             {**reason, 'expected_latest_revision': 2, 'parent_revision': 5, 'content': content}, (7,)),
            ('POST', '/api/recipe-revisions/5/transition', 'transition', RecipeTransition,
             {**reason, 'expected_version': 2, 'action': 'approve'}, (5,)),
            ('POST', '/api/recipes/select', 'select', RecipeSelect,
             {**reason, 'revision_id': None, 'expected_selection_version': 2}, ()),
            ('PUT', '/api/recipes/policy', 'update_policy', PolicyChange,
             {**reason, 'expected_version': 2, 'policy': {'editing_enabled': False}}, ()),
            ('POST', '/api/recipes/simulator-permit', 'simulator_permit', SimulationPermit,
             {**reason, 'allowed': False}, ()),
        ]

    def test_public_reads_and_typed_mutations_forward_identity_without_policy_duplication(self):
        app, client, service, user, invoke = self.fixture()
        for path, name in (('/api/recipes', 'snapshot'), ('/api/recipes/selected', 'selected')):
            self.assertEqual(client.get(path).json(), {'result': name})
            getattr(service, name).assert_called_once_with()
        user.assert_not_called(); invoke.assert_not_called()
        for method, path, name, model, body, prefix in self.cases():
            with self.subTest(path=path):
                response = client.request(method, path, json=body)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json(), {'result': name})
                arguments = getattr(service, name).call_args.args
                self.assertEqual(arguments[:-2], prefix)
                self.assertIs(type(arguments[-2]), model)
                self.assertEqual(arguments[-2], model.model_validate(body))
                self.assertIs(arguments[-1], user.return_value)
                self.assertIs(invoke.call_args.args[0], getattr(service, name))
        self.assertFalse(hasattr(app.state, 'recipes'))
        self.assertEqual(user.call_count, 6)

    def test_validation_and_identity_failures_never_invoke_mutations(self):
        _, client, service, user, invoke = self.fixture()
        for method, path, name, _, body, _ in self.cases():
            for invalid in ({**body, 'reason': ' '}, {**body, 'extra_field': True}):
                with self.subTest(path=path, invalid=invalid):
                    self.assertEqual(client.request(method, path, json=invalid).status_code, 422)
            getattr(service, name).assert_not_called()
        self.assertEqual(client.post('/api/recipes/not-an-integer/revisions', json=self.cases()[1][4]).status_code, 422)
        user.assert_not_called(); invoke.assert_not_called()
        user.side_effect = HTTPException(401, 'Sign in first')
        for method, path, name, _, body, _ in self.cases():
            self.assertEqual(client.request(method, path, json=body).status_code, 401)
            getattr(service, name).assert_not_called()
        invoke.assert_not_called()
        user.side_effect = None
        invoke.side_effect = HTTPException(423, 'Policy blocks change')
        response = client.post('/api/recipes', json=self.cases()[0][4])
        self.assertEqual((response.status_code, response.json()['detail']), (423, 'Policy blocks change'))
        service.create.assert_not_called()

    def test_canonical_models_and_focused_import_boundary(self):
        app, _, _, _, _ = self.fixture()
        schema = app.openapi()
        for method, path, _, model, _, _ in self.cases():
            self.assertEqual(model.__module__, 'openhmi.recipe_models')
            template = path.replace('/7/', '/{recipe_id}/').replace('/5/', '/{revision_id}/')
            self.assertEqual(schema['paths'][template][method.lower()]['requestBody']['content']['application/json']['schema'],
                             {'$ref': '#/components/schemas/' + model.__name__})
        code = "import json,sys; import openhmi.recipe_library_routes; print(json.dumps([name for name in ('openhmi.recipe_routes','openhmi.recipes','openhmi.recipe_transfers','openhmi.server','PIL','pycomm3') if name in sys.modules]))"
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=30, check=True)
        self.assertEqual(json.loads(result.stdout), [])
