"""Browser transfer requests through real SQL/HTTP with simulator-only staging."""
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from openhmi.recipe_models import RecipeTransfer
from openhmi.server import create_app
from tests.test_commands import install
from tests.test_frontend_contract import frontend
from tests.test_recipe_transfers import transfer_project, content
from tests.test_recipes import USERS, PASSWORD


def recipe_transfer_fixture(test_case):
    app = create_app(recipe_users=USERS)
    test_case.addCleanup(app.state.store.close)
    test_case.addCleanup(app.state.driver.close)
    app.state.driver.factory = Mock(side_effect=AssertionError('Contract cannot open a PLC connection'))
    client = TestClient(app)  # Explicit simulator polls; no background workers.
    test_case.addCleanup(client.close)
    install(client, transfer_project(client.get('/api/project').json()['draft']))
    client.post('/api/recipe-auth/login', json={'name': 'engineer', 'password': PASSWORD}).raise_for_status()
    revision = client.post('/api/recipes', json={'code': 'FIXTURE', 'content': content(), 'reason': 'Offline fixture'}).json()
    test_case.instance = app.state.project_instance
    return app, client, revision


class RecipeTransferContractTests(unittest.TestCase):
    def fixture(self):
        return recipe_transfer_fixture(self)

    def browser(self, **kwargs):
        return frontend('recipe_transfers', projectInstance=getattr(self, 'instance', 'a' * 32), **kwargs)

    def send(self, client, request):
        self.assertTrue(request['timed'])
        self.assertEqual(request['headers']['X-OpenHMI-Project'], self.instance)
        return client.request(request.get('method', 'GET'), request['path'], headers=request['headers'],
                              **({'json': request['body']} if 'body' in request else {}))

    def dispatch(self, revision, project=2, **kwargs):
        return dict(profile='product', revision=revision['id'], version=revision['version'], project=project,
                    reason=' Offline transfer Δ ', **kwargs)

    def test_generated_dispatch_receipt_sql_history_filters_detail_and_json_export(self):
        app, client, revision = self.fixture()
        active = app.state.store.snapshot()['active_revision']
        payload = self.dispatch(revision, active)
        request = self.browser(dispatches=[payload])['requests'][0]
        RecipeTransfer.model_validate(request['body'])
        app.state.driver.poll()
        response = self.send(client, request)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers['X-OpenHMI-Audit-Status'], 'succeeded')
        self.assertEqual(response.headers['X-OpenHMI-Operation-ID'], response.json()['transaction']['operation_id'])
        record = response.json()['transfer']
        identifier = record['id']
        self.assertEqual(record['snapshot']['transferred_by'], 'engineer')
        self.assertEqual(record['snapshot']['transfer_reason'], payload['reason'])
        self.assertFalse(record['snapshot']['production_approved'])
        app.state.recipe_transfers.recent = Mock(wraps=app.state.recipe_transfers.recent)
        queries = [{}, dict(filters={'profile': 'product', 'production': 'false'}, before='9223372036854775807', verified='product', options={'limit': 1}),
                   dict(filters={'production': 'true'}, options={'limit': 100}),
                   dict(filters={'profile': '设备 A,+%?', 'production': 'false'}, verified='设备 +%')]
        result = self.browser(queries=queries, details=[dict(id=str(identifier)), dict(id=str(identifier), options={'download': True})])
        self.assertEqual(result['histories'][0], 'limit=25')
        for query, history, generated in zip(queries, result['histories'], result['requests']):
            self.assertNotIn('verified_profile', parse_qs(history))
            response = self.send(client, generated)
            self.assertEqual(response.status_code, 200, response.text)
            params = parse_qs(urlsplit(generated['path']).query)
            app.state.recipe_transfers.recent.assert_called_with(int(params['limit'][0]),
                int(params['before_id'][0]) if 'before_id' in params else None, params.get('profile_id', [''])[0],
                {'true': True, 'false': False}.get(params.get('production_approved', [''])[0]), params.get('verified_profile', [''])[0])
            if query.get('verified') == 'product': self.assertEqual(response.json()['items'][0]['id'], identifier)
        detail = self.send(client, result['requests'][-2])
        self.assertEqual(detail.json()['id'], identifier)
        exported = self.send(client, result['requests'][-1])
        self.assertEqual(exported.json()['format'], 'openhmi.recipe-transfer')
        self.assertEqual(exported.json()['transfer'], detail.json())
        self.assertIn(f'openhmi-recipe-transfer-{identifier}.json', exported.headers['content-disposition'])
        self.assertEqual(exported.headers['cache-control'], 'no-store')
        app.state.driver.factory.assert_not_called()

    def test_invalid_generated_bounds_and_stale_dispatches_fail_before_staging(self):
        app, client, revision = self.fixture()
        transfers = app.state.recipe_transfers
        transfers.recent = Mock(wraps=transfers.recent)
        transfers.get = Mock(wraps=transfers.get)
        transfers.submit = Mock(wraps=transfers.submit)
        queries = [dict(options={'limit': value}) for value in (0, 101)] + [dict(before=value) for value in ('-1', '9223372036854775808')]
        queries += [dict(filters={'profile': 'x' * 61}), dict(filters={'production': 'unknown'}), dict(verified='x' * 61)]
        result = self.browser(queries=queries, details=[dict(id=value) for value in ('0', '1.5', '9223372036854775808')])
        for request in result['requests']: self.assertEqual(self.send(client, request).status_code, 422)
        transfers.recent.assert_not_called()
        transfers.get.assert_not_called()
        base = self.dispatch(revision, app.state.store.snapshot()['active_revision'])
        invalid = [{**base, key: value} for key, value in [('revision', 2147483648), ('version', True), ('project', 0), ('reason', ' ')]]
        for request in self.browser(dispatches=invalid)['requests']: self.assertEqual(self.send(client, request).status_code, 422)
        transfers.submit.assert_not_called()
        app.state.driver.write_recipe_member = Mock(wraps=app.state.driver.write_recipe_member)
        for item, status in [({**base, 'project': base['project'] - 1}, 409), ({**base, 'version': 100}, 409), ({**base, 'profile': 'missing'}, 404)]:
            request = self.browser(dispatches=[item])['requests'][0]
            self.assertEqual(self.send(client, request).status_code, status)
        client.post('/api/recipe-auth/logout', json={}).raise_for_status()
        for request in self.browser(queries=[{}], dispatches=[base])['requests']:
            self.assertEqual(self.send(client, request).status_code, 401)
        app.state.driver.write_recipe_member.assert_not_called()
        app.state.driver.factory.assert_not_called()

    def test_encoded_target_precise_ids_and_errors_do_not_replay(self):
        payload = dict(profile='设备 +%/?', revision=2147483647, version=1, project=9007199254740991, reason=' Reason Δ ')
        result = self.browser(dispatches=[payload], details=[dict(id='9223372036854775807', options={'download': True})])
        self.assertEqual(result['requests'][0]['path'], '/api/recipe-transfers/9223372036854775807?download=true')
        self.assertEqual(result['requests'][1]['path'], '/api/recipe-transfers/%E8%AE%BE%E5%A4%87%20%2B%25%2F%3F/dispatch')
        RecipeTransfer.model_validate(result['requests'][1]['body'])
        for status in (401, 403, 409, 422, 503):
            result = self.browser(dispatches=[payload], status=status)
            self.assertEqual(len(result['requests']), 1)
            self.assertEqual(result['results'], [dict(error='Synthetic denial', status=status, operation_id='b' * 32, audit_status='denied')])


if __name__ == '__main__':
    unittest.main()
