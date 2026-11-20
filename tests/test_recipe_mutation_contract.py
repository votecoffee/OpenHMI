"""Production recipe serializers through strict models and SQL-backed routes."""
from copy import deepcopy
from threading import RLock
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openhmi.projects import ProjectStore
from openhmi.recipe_auth import RecipeUser
from openhmi.recipe_models import RecipeCreate, RecipeSave, RecipeSelect, RecipeTransition
from openhmi.recipe_routes import add_recipe_routes
from tests.test_frontend_contract import frontend


def editor_content():
    return dict(title='设备 Recipe Δ', description='Offline fixture', image_id=None, parameters=[
        dict(name='speed', label='Speed', type='number', value='12.125', unit='rpm', minimum='0', maximum='100'),
        dict(name='count', label='Count', type='integer', value='0', minimum='', maximum=None),
        dict(name='enabled', label='Enabled', type='boolean', value=False),
        dict(name='serial', label='Serial', type='text', value='001,设备\nΔ'),
    ])


class RecipeMutationContractTests(unittest.TestCase):
    def fixture(self):
        store = ProjectStore()
        self.addCleanup(store.close)
        driver = Mock(spec=['load_recipe', 'read'])
        driver.read.side_effect = AssertionError('Contract cannot read controller tags')
        application = SimpleNamespace(lock=RLock(), driver=driver)
        user = RecipeUser('Fixture Engineer Δ', frozenset({'engineer', 'approver', 'operator'}))
        security = SimpleNamespace(configured=lambda: True, user=Mock(return_value=user))
        app = FastAPI()
        add_recipe_routes(app, store, application, security=security, commands=SimpleNamespace())
        client = TestClient(app)
        self.addCleanup(client.close)
        driver.reset_mock()
        service = app.state.recipes
        for name in ('create', 'save', 'transition', 'select'):
            setattr(service, name, Mock(wraps=getattr(service, name)))
        return client, service, security, driver

    def browser(self, mutations, **kwargs):
        return frontend('recipe_mutations', mutations=[{**item, 'reason': item.get('reason', ' Offline review Δ ')}
                                                     for item in mutations], **kwargs)

    def send(self, client, request):
        self.assertEqual(request['method'], 'POST')
        self.assertTrue(request['timed'])
        self.assertEqual(request['headers'], {'Content-Type': 'application/json', 'X-OpenHMI-Project': 'a' * 32})
        return client.post(request['path'], json=request['body'])

    def test_generated_requests_preserve_review_versions_and_independent_selected_copies(self):
        client, service, _, driver = self.fixture()
        operations = [dict(action='create', code='FIXTURE', content=editor_content()),
            dict(action='select', id=1, version=1, selection=1),
            dict(action='transition', id=1, transition='submit', version=1),
            dict(action='transition', id=1, transition='approve', version=2),
            dict(action='select', id=1, version=3, selection=2),
            dict(action='revise', recipe=1, latest=1, parent=1, content={**editor_content(), 'title': 'Revision 2'}),
            dict(action='transition', id=1, transition='withdraw', version=3),
            dict(action='transition', id=2, transition='submit', version=1),
            dict(action='transition', id=2, transition='reject', version=2),
            dict(action='select', id=None, version=None, selection=3)]
        requests = self.browser(operations)['requests']
        results = []
        for index, request in enumerate(requests):
            model = RecipeCreate if index == 0 else RecipeSave if index == 5 else RecipeSelect if index in (1, 4, 9) else RecipeTransition
            model.model_validate(request['body'])
            response = self.send(client, request)
            self.assertEqual(response.status_code, 200, response.text)
            results.append(response.json())
            if index in (3, 5, 6):
                loaded = service.selected()['snapshot']
                self.assertEqual(loaded['content']['title'], '设备 Recipe Δ')
                self.assertEqual(loaded['production_approved'], index != 3)
        self.assertEqual(results[0]['author'], 'Fixture Engineer Δ')
        self.assertEqual(results[3]['approved_by'], results[0]['author'], 'Same-user approval remains supported')
        self.assertEqual(results[5]['parent_revision'], 1)
        self.assertEqual(results[8]['status'], 'rejected')
        self.assertEqual(results[-1], {'version': 4, 'snapshot': None})
        self.assertEqual(driver.load_recipe.call_count, 3)
        driver.read.assert_not_called()
        stale = self.browser([dict(action='revise', recipe=1, latest=1, parent=1, content=editor_content()),
                              dict(action='transition', id=1, transition='withdraw', version=3),
                              dict(action='select', id=1, version=4, selection=1)])['requests']
        audit_before = service.snapshot()['audit']
        for request in stale: self.assertEqual(self.send(client, request).status_code, 409)
        self.assertEqual(service.snapshot()['audit'], audit_before)
        self.assertEqual(driver.load_recipe.call_count, 3)

    def test_normalization_is_lossless_for_supported_values_and_blank_numeric_fails_before_fetch(self):
        content = editor_content()
        content['parameters'] += [dict(name='low', label='Low', type='integer', value=str(-(2**53 - 1))),
                                  dict(name='high', label='High', type='integer', value=str(2**53 - 1)),
                                  dict(name='empty', label='Empty', type='text', value='')]
        reply = self.browser([dict(action='create', code='FIXTURE', content=content)])
        model = RecipeCreate.model_validate(reply['requests'][0]['body'])
        self.assertEqual([parameter.value for parameter in model.content.parameters],
                         [12.125, 0, False, '001,设备\nΔ', -(2**53 - 1), 2**53 - 1, ''])
        self.assertEqual((model.content.parameters[0].minimum, model.content.parameters[0].maximum), (0, 100))
        self.assertIsNone(model.content.parameters[1].minimum)
        self.assertEqual(model.reason, ' Offline review Δ ')
        for value in ('', '  '):
            blank = deepcopy(content)
            blank['parameters'][0]['value'] = value
            result = self.browser([dict(action='create', code='FIXTURE', content=blank)])
            self.assertEqual(result['requests'], [])
            self.assertEqual(result['results'], [{'error': 'Enter a value for Speed'}])

    def test_invalid_payloads_fail_before_services_and_denied_requests_cannot_publish(self):
        client, service, security, driver = self.fixture()
        invalid = [dict(action='create', code='bad code', content=editor_content()),
                   dict(action='create', code='FIXTURE', content=editor_content(), reason='  '),
                   dict(action='revise', recipe=1, latest=0, parent=1, content=editor_content()),
                   dict(action='transition', id=1, transition='invented', version=1),
                   dict(action='transition', id=1, transition='submit', version=True),
                   dict(action='select', id=0, version=1, selection=1),
                   dict(action='select', id=1, version=1, selection='1')]
        for value in ('not-a-number', '100.1'):
            content = editor_content()
            content['parameters'][0]['value'] = value
            invalid.append(dict(action='create', code='FIXTURE', content=content))
        for request in self.browser(invalid)['requests']:
            self.assertEqual(self.send(client, request).status_code, 422)
        for name in ('create', 'save', 'transition', 'select'): getattr(service, name).assert_not_called()
        valid = self.browser([dict(action='create', code='FIXTURE', content=editor_content()),
                              dict(action='revise', recipe=1, latest=1, parent=1, content=editor_content()),
                              dict(action='transition', id=1, transition='approve', version=1),
                              dict(action='select', id=None, version=None, selection=1)])['requests']
        for user, status in ((None, 401), (RecipeUser('Limited', frozenset()), 403)):
            security.user.return_value = user
            for request in valid: self.assertEqual(self.send(client, request).status_code, status)
        self.assertEqual(service.snapshot()['audit'], [])
        driver.load_recipe.assert_not_called()
        driver.read.assert_not_called()

    def test_http_errors_and_receipts_propagate_without_replay(self):
        operations = [dict(action='create', code='FIXTURE', content=editor_content()),
                      dict(action='revise', recipe='9223372036854775807', latest=1, parent=1, content=editor_content()),
                      dict(action='transition', id='9223372036854775807', transition='submit', version=1),
                      dict(action='select', id=None, version=None, selection=1)]
        reply = self.browser(operations)
        self.assertEqual(reply['requests'][1]['path'], '/api/recipes/9223372036854775807/revisions')
        self.assertEqual(reply['requests'][2]['path'], '/api/recipe-revisions/9223372036854775807/transition')
        self.assertEqual(reply['requests'][-1]['body'], dict(revision_id=None, expected_revision_version=None,
                                                           expected_selection_version=1, reason=' Offline review Δ '))
        self.assertTrue(all(item['operation_id'] == 'b' * 32 and item['audit_status'] == 'pending' for item in reply['results']))
        for status in (401, 403, 409, 422, 503):
            result = self.browser(operations, status=status)
            self.assertEqual(len(result['requests']), 4)
            self.assertTrue(all(item == dict(error='Synthetic denial', status=status, operation_id='b' * 32,
                                             audit_status='denied') for item in result['results']))


if __name__ == '__main__':
    unittest.main()
