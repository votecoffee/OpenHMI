"""Image HTTP adapter boundaries independent of recipe persistence and drivers."""
import asyncio
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, AsyncMock

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from openhmi.recipe_auth import RecipeUser
from openhmi.recipe_image_routes import add_recipe_image_routes


class RecipeImageRouteTests(unittest.TestCase):
    def fixture(self):
        app = FastAPI()
        service = SimpleNamespace(image=Mock(return_value=b'fixture image bytes'),
                                  add_image=Mock(return_value={'image_id': 'a' * 64, 'width': 2, 'height': 1}))
        principal = RecipeUser('Fixture Engineer', frozenset({'engineer'}))
        user = Mock(return_value=principal)
        invoke = Mock(side_effect=lambda method, *args: method(*args))
        add_recipe_image_routes(app, service, user, invoke)
        client = TestClient(app)
        self.addCleanup(client.close)
        return app, client, service, user, invoke

    def test_public_reads_and_protected_upload_preserve_headers_bytes_and_identity(self):
        app, client, service, user, invoke = self.fixture()
        response = client.get('/api/recipe-images/' + 'a' * 64)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'fixture image bytes')
        self.assertEqual(response.headers['content-type'], 'image/png')
        self.assertEqual(response.headers['cache-control'], 'public,max-age=31536000,immutable')
        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        user.assert_not_called()
        service.image.assert_called_once_with('a' * 64)
        payload = b'\x00\xff\x01fixture'
        response = client.post('/api/recipe-images', params={'reason': ' 设备,+% reason '}, content=payload,
                               headers={'Content-Type': 'image/jpeg; charset=binary'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['image_id'], 'a' * 64)
        service.add_image.assert_called_once_with(payload, ' 设备,+% reason ', user.return_value)
        self.assertIs(invoke.call_args.args[0], service.add_image)
        self.assertFalse(hasattr(app.state, 'recipes'))

    def test_validation_role_and_http_limit_failures_precede_service_dispatch(self):
        _, client, service, user, _ = self.fixture()
        for reason in ('', 'x' * 1001):
            self.assertEqual(client.post('/api/recipe-images', params={'reason': reason}, content=b'x',
                             headers={'Content-Type': 'image/png'}).status_code, 422)
        user.assert_not_called()
        user.side_effect = HTTPException(401, 'Sign in first')
        self.assertEqual(client.post('/api/recipe-images?reason=Fixture', content=b'x', headers={'Content-Type': 'image/png'}).status_code, 401)
        user.side_effect = None
        user.return_value = RecipeUser('Operator', frozenset({'operator'}))
        self.assertEqual(client.post('/api/recipe-images?reason=Fixture', content=b'x', headers={'Content-Type': 'image/png'}).status_code, 403)
        user.return_value = RecipeUser('Engineer', frozenset({'engineer'}))
        self.assertEqual(client.post('/api/recipe-images?reason=Fixture', content=b'x', headers={'Content-Type': 'image/gif'}).status_code, 415)
        self.assertEqual(client.post('/api/recipe-images?reason=%20', content=b'x', headers={'Content-Type': 'image/png'}).status_code, 422)
        service.add_image.assert_not_called()
        boundary = b'x' * (5 * 1024 * 1024)
        self.assertEqual(client.post('/api/recipe-images?reason=Fixture', content=boundary, headers={'Content-Type': 'image/png'}).status_code, 200)
        service.add_image.reset_mock()
        self.assertEqual(client.post('/api/recipe-images?reason=Fixture', content=boundary + b'x', headers={'Content-Type': 'image/png'}).status_code, 413)
        service.add_image.assert_not_called()
        service.image.side_effect = HTTPException(404, 'Image missing')
        self.assertEqual(client.get('/api/recipe-images/missing').status_code, 404)

    def test_streaming_stops_after_overflow_and_focused_imports_stay_isolated(self):
        app, _, service, _, _ = self.fixture()
        receive = AsyncMock(side_effect=[
            {'type': 'http.request', 'body': b'x' * (5 * 1024 * 1024), 'more_body': True},
            {'type': 'http.request', 'body': b'x', 'more_body': True},
            {'type': 'http.request', 'body': b'must not be consumed', 'more_body': False},
        ])
        request = Request({'type': 'http', 'method': 'POST', 'path': '/api/recipe-images',
                           'headers': [(b'content-type', b'image/png')]}, receive)
        endpoint = next(route.endpoint for route in app.routes if getattr(route, 'path', None) == '/api/recipe-images')
        with self.assertRaises(HTTPException) as failure:
            asyncio.run(endpoint(request, 'Fixture'))
        self.assertEqual(failure.exception.status_code, 413)
        self.assertEqual(receive.await_count, 2)
        service.add_image.assert_not_called()
        code = "import json,sys; import openhmi.recipe_image_routes; print(json.dumps([name for name in ('openhmi.recipe_routes','openhmi.recipes','openhmi.recipe_transfers','openhmi.server','PIL') if name in sys.modules]))"
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=30, check=True)
        self.assertEqual(json.loads(result.stdout), [])


if __name__ == '__main__':
    unittest.main()
