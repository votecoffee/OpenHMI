"""Recipe policy and raw image uploads use the production browser helpers."""
from io import BytesIO
import unittest
from unittest.mock import Mock

from PIL import Image
from openhmi.recipe_auth import RecipeUser
from openhmi.recipe_models import PolicyChange
from tests.test_frontend_contract import frontend
from tests.test_recipe_mutation_contract import recipe_route_fixture


class RecipeSettingsContractTests(unittest.TestCase):
    def fixture(self):
        client, service, security, driver = recipe_route_fixture(self)
        security.user.return_value = RecipeUser('Fixture Administrator Δ', frozenset({'administrator'}))
        for name in ('update_policy', 'add_image'):
            setattr(service, name, Mock(wraps=getattr(service, name)))
        return client, service, security, driver

    def browser(self, operations, **kwargs):
        return frontend('recipe_mutations', mutations=[{'reason': ' 设备 review,+%?&#\nΔ ', **item}
                                                     for item in operations], **kwargs)

    def image(self, kind='PNG', **kwargs):
        output = BytesIO()
        Image.new('RGB', (3, 2), '#123456').save(output, format=kind)
        return dict(action='image', name='设备.' + kind.lower(), type='image/' + kind.lower(),
                    bytes=list(output.getvalue()), **kwargs)

    def send(self, client, request):
        self.assertTrue(request['timed'])
        self.assertEqual(request['headers']['X-OpenHMI-Project'], 'a' * 32)
        if 'upload' in request:
            self.assertEqual(request['method'], 'POST')
            return client.post(request['path'], content=bytes(request['upload']['bytes']), headers=request['headers'])
        self.assertEqual(request['method'], 'PUT')
        self.assertEqual(request['headers']['Content-Type'], 'application/json')
        return client.put(request['path'], json=request['body'])

    def test_policy_versions_defaults_permit_cache_and_server_attributed_history(self):
        client, service, _, driver = self.fixture()
        driver.read.side_effect = None
        driver.read.return_value = [True]
        policy = dict(editing_enabled=False, approval_enabled=True, loading_enabled=True,
                      editing_permit_tag=None, approval_permit_tag='RecipePermit', loading_permit_tag=None)
        request = self.browser([dict(action='policy', policy=policy, version=1)])['requests'][0]
        PolicyChange.model_validate(request['body'])
        response = self.send(client, request)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), dict(version=2, policy=policy))
        driver.read.assert_called_once_with('RecipePermit')
        self.assertEqual(self.send(client, request).status_code, 409)
        driver.read.assert_called_once_with('RecipePermit')
        event = service.snapshot()['audit'][0]
        self.assertEqual((event['operation'], event['actor']), ('policy_changed', 'Fixture Administrator Δ'))
        self.assertEqual(event['details']['reason'], request['body']['reason'])
        reset = self.browser([dict(action='policy', policy={}, version=2)])['requests'][0]
        self.assertEqual(self.send(client, reset).json()['policy'], PolicyChange.model_validate(reset['body']).policy.model_dump())
        driver.load_recipe.assert_not_called()

    def test_png_jpeg_bytes_reason_encoding_and_normalized_image_round_trip(self):
        client, service, _, driver = self.fixture()
        operations = [self.image('PNG'), self.image('JPEG')]
        requests = self.browser(operations)['requests']
        for operation, request in zip(operations, requests):
            self.assertEqual(request['upload']['bytes'], operation['bytes'])
            self.assertEqual(request['upload']['type'], operation['type'])
            self.assertEqual(request['headers']['Content-Type'], operation['type'])
            self.assertTrue(request['timeout'])
            self.assertEqual(request['path'], '/api/recipe-images?reason=%20%E8%AE%BE%E5%A4%87%20review%2C%2B%25%3F%26%23%0A%CE%94%20')
            response = self.send(client, request)
            self.assertEqual(response.status_code, 200, response.text)
            identifier = response.json()['image_id']
            self.assertRegex(identifier, r'^[a-f0-9]{64}$')
            picture = client.get('/api/recipe-images/' + identifier)
            self.assertEqual(picture.headers['content-type'], 'image/png')
            with Image.open(BytesIO(picture.content)) as image:
                self.assertEqual((image.format, image.size), ('PNG', (3, 2)))
        self.assertEqual(service.add_image.call_count, 2)
        self.assertTrue(all(event['actor'] == 'Fixture Administrator Δ' for event in service.snapshot()['audit']))
        driver.read.assert_not_called()
        driver.load_recipe.assert_not_called()

    def test_invalid_models_upload_limits_roles_and_closed_edit_gate(self):
        client, service, security, driver = self.fixture()
        invalid = [dict(action='policy', policy={'editing_enabled': 'false'}, version=1),
                   dict(action='policy', policy={'invented': True}, version=1),
                   dict(action='policy', policy={}, version=True),
                   dict(action='policy', policy={}, version=0),
                   dict(action='policy', policy={}, version=1, reason=' ')]
        for request in self.browser(invalid)['requests']:
            self.assertEqual(self.send(client, request).status_code, 422)
        service.update_policy.assert_not_called()
        bad = [self.image(reason=''), self.image(reason=' '), self.image(reason='x' * 1001),
               dict(action='image', name='bad.svg', type='image/svg+xml', bytes=[60, 62])]
        for request, expected in zip(self.browser(bad)['requests'], (422, 422, 422, 415)):
            self.assertEqual(self.send(client, request).status_code, expected)
        service.add_image.assert_not_called()
        # Generate the actual upload URL/headers, then exercise the HTTP stream limit
        # without serializing a multi-megabyte byte array through the Node harness.
        request = self.browser([self.image()])['requests'][0]
        response = client.post(request['path'], content=b'x' * (5 * 1024 * 1024 + 1), headers=request['headers'])
        self.assertEqual(response.status_code, 413)
        service.add_image.assert_not_called()
        malformed = {**request, 'upload': {**request['upload'], 'bytes': [0, 1, 2]}}
        self.assertEqual(self.send(client, malformed).status_code, 422)
        valid = self.browser([dict(action='policy', policy={}, version=1), self.image()])['requests']
        for user, status in ((None, 401), (RecipeUser('Operator', frozenset({'operator'})), 403)):
            security.user.return_value = user
            for request in valid: self.assertEqual(self.send(client, request).status_code, status)
        security.user.return_value = RecipeUser('Engineer', frozenset({'engineer'}))
        self.assertEqual(self.send(client, valid[0]).status_code, 403)
        security.user.return_value = RecipeUser('Administrator', frozenset({'administrator'}))
        freeze = self.browser([dict(action='policy', policy={'editing_enabled': False}, version=1)])['requests'][0]
        self.assertEqual(self.send(client, freeze).status_code, 200)
        self.assertEqual(self.send(client, valid[1]).status_code, 423)
        self.assertEqual([event['operation'] for event in service.snapshot()['audit']], ['policy_changed'])
        driver.read.assert_not_called()
        driver.load_recipe.assert_not_called()

    def test_optional_receipts_and_http_errors_propagate_without_replay(self):
        operations = [dict(action='policy', policy={}, version=1), self.image()]
        result = self.browser(operations)
        self.assertTrue(all(item['operation_id'] == 'b' * 32 and item['audit_status'] == 'pending' for item in result['results']))
        for status in (401, 403, 409, 413, 415, 422, 503):
            result = self.browser(operations, status=status)
            self.assertEqual(len(result['requests']), 2)
            self.assertTrue(all(item == dict(error='Synthetic denial', status=status, operation_id='b' * 32,
                                             audit_status='denied') for item in result['results']))


if __name__ == '__main__':
    unittest.main()
