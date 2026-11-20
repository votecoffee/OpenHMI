"""Focused recipe authentication registrar; no recipe service or driver is needed."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from openhmi.recipe_auth import RecipeAuth
from openhmi.recipe_auth_routes import add_recipe_auth_routes, require_recipe_user, COOKIE, APP_COOKIE
from openhmi.recipe_routes import Login, Empty
from openhmi.projects import ProjectStore
from openhmi.security import Security
from openhmi.security_routes import SecurityChange
from openhmi.server import create_app
from tests.test_recipes import USERS, PASSWORD
from tests.test_security import FakeWindows, PASSWORD as HMI_PASSWORD


class RecipeAuthRouteTests(unittest.TestCase):
    def client(self, security=None):
        auth = RecipeAuth(USERS)
        app = FastAPI()
        add_recipe_auth_routes(app, auth, security, Login, Empty)
        @app.post('/probe')
        def probe(request: Request):
            return {'name': require_recipe_user(request, auth, security).name}
        client = TestClient(app, base_url='https://testserver')
        self.addCleanup(client.close)
        return app, auth, client

    def test_standalone_local_cookie_origin_rate_limit_and_shared_authorizer(self):
        app, auth, client = self.client()
        self.assertFalse(hasattr(app.state, 'recipes'))
        self.assertFalse(hasattr(app.state, 'recipe_transfers'))
        self.assertEqual(client.get('/api/recipes').status_code, 404)
        self.assertEqual(client.post('/api/recipe-auth/logout', json={}).status_code, 401)
        login = dict(name='engineer', password=PASSWORD)
        auth.login = Mock(wraps=auth.login)
        self.assertEqual(client.post('/api/recipe-auth/login', json=login, headers={'Origin': 'https://example.invalid'}).status_code, 403)
        self.assertEqual(client.post('/api/recipe-auth/login', json={**login, 'roles': ['administrator']}).status_code, 422)
        auth.login.assert_not_called()
        response = client.post('/api/recipe-auth/login', json=login)
        self.assertEqual(response.status_code, 200, response.text)
        for attribute in ('HttpOnly', 'SameSite=strict', 'Secure', 'Max-Age=3600'):
            self.assertIn(attribute, response.headers['set-cookie'])
        self.assertIsNotNone(client.cookies.get(COOKIE))
        self.assertEqual(client.post('/probe').json(), {'name': 'engineer'})
        self.assertEqual(client.post('/probe', headers={'Origin': 'https://example.invalid'}).status_code, 403)
        self.assertEqual(client.post('/api/recipe-auth/logout', json={}).status_code, 200)
        self.assertIsNone(client.cookies.get(COOKIE))
        self.assertEqual(client.post('/probe').status_code, 401)
        auth.login.side_effect = ValueError('Synthetic login limit')
        self.assertEqual(client.post('/api/recipe-auth/login', json=login).status_code, 429)

    def test_hmi_delegation_ignores_legacy_cookie_and_preserves_idempotent_hmi_logout(self):
        store = ProjectStore()
        self.addCleanup(store.close)
        security = Security(store, windows=FakeWindows())
        _, _, client = self.client(security)
        client.post('/api/recipe-auth/login', json={'name': 'engineer', 'password': PASSWORD}).raise_for_status()
        self.assertIsNotNone(client.cookies.get(COOKIE))
        security.change(SecurityChange(operation='user', expected_version=security.snapshot()['version'], name='admin',
                                       groups=['Administrators'], password=HMI_PASSWORD, reason='Offline bootstrap'), 'test-console')
        self.assertIsNone(client.get('/api/recipe-auth/session').json()['user'])
        self.assertEqual(client.post('/probe').status_code, 401)
        response = client.post('/api/recipe-auth/login', json={'name': 'admin', 'password': HMI_PASSWORD})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn(APP_COOKIE, response.headers['set-cookie'])
        self.assertEqual(client.get('/api/recipe-auth/session').json()['user']['provider'], 'local')
        self.assertEqual(client.post('/probe').json(), {'name': 'admin'})
        self.assertEqual(client.post('/api/recipe-auth/logout', json={}, headers={'Origin': 'https://example.invalid'}).status_code, 403)
        self.assertEqual(client.post('/api/recipe-auth/logout', json={}).status_code, 200)
        self.assertEqual(client.post('/api/recipe-auth/logout', json={}).status_code, 200)
        self.assertIsNone(client.get('/api/recipe-auth/session').json()['user'])

    def test_model_ownership_openapi_references_and_focused_import_boundary(self):
        self.assertEqual(Login.__module__, 'openhmi.recipe_routes')
        self.assertEqual(Empty.__module__, 'openhmi.recipe_routes')
        app = create_app()
        self.addCleanup(app.state.store.close)
        self.addCleanup(app.state.driver.close)
        schema = app.openapi()
        self.assertEqual(schema['paths']['/api/recipe-auth/login']['post']['requestBody']['content']['application/json']['schema'],
                         {'$ref': '#/components/schemas/openhmi__recipe_routes__Login'})
        for path in ('/api/recipe-auth/session', '/api/recipe-auth/login', '/api/recipe-auth/logout'):
            endpoints = [route for route in app.routes if getattr(route, 'path', None) == path]
            self.assertEqual(len(endpoints), 1)
            self.assertEqual(endpoints[0].endpoint.__module__, 'openhmi.recipe_auth_routes')
        code = "import json,sys; import openhmi.recipe_auth_routes; print(json.dumps([name for name in ('openhmi.recipe_routes','openhmi.recipes','openhmi.recipe_transfers','openhmi.server') if name in sys.modules]))"
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=30, check=True)
        self.assertEqual(json.loads(result.stdout), [])


if __name__ == '__main__':
    unittest.main()
