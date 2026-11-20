"""Dispatch receipt correlation and ambiguous outcomes never replay a transfer."""
from copy import deepcopy
import sqlite3
import unittest
from unittest.mock import patch

from tests.test_frontend_contract import frontend
from tests.test_recipe_transfer_contract import recipe_transfer_fixture


class RecipeTransferReceiptTests(unittest.TestCase):
    def validate(self, entries=(), errors=()):
        return frontend('recipe_transfer_receipts', entries=list(entries), errors=list(errors))

    def request(self, app, revision):
        return dict(revision_id=revision['id'], expected_revision_version=revision['version'],
                    expected_project_revision=app.state.store.snapshot()['active_revision'], reason='Offline receipt fixture')

    def expected(self, revision):
        return dict(profileId='product', revisionId=revision['id'], revisionVersion=revision['version'])

    def receipt(self, response):
        return {**response.json(), 'operation_id': response.headers['X-OpenHMI-Operation-ID'],
                'audit_status': response.headers['X-OpenHMI-Audit-Status']}

    def test_real_success_pending_audit_and_legacy_headerless_receipts_match_request(self):
        entries = []
        for pending in (False, True):
            app, client, revision = recipe_transfer_fixture(self)
            app.state.driver.poll()
            if pending:
                with patch.object(app.state.activity, 'finish', side_effect=sqlite3.OperationalError('Synthetic finalization outage')):
                    with self.assertLogs(level='ERROR'):
                        response = client.post('/api/recipe-transfers/product/dispatch', json=self.request(app, revision))
            else:
                response = client.post('/api/recipe-transfers/product/dispatch', json=self.request(app, revision))
            self.assertEqual(response.status_code, 200, response.text)
            data = self.receipt(response)
            self.assertEqual(data['audit_status'], 'pending' if pending else 'succeeded')
            self.assertEqual(data['transaction']['state'], 'requested')
            entries.extend([dict(data=data, expected=self.expected(revision)),
                            dict(data=response.json(), expected=self.expected(revision))])
            self.assertEqual(app.state.driver._tags['CycleCommand']['RequestSequence'], 1)
            self.assertEqual(len(client.get('/api/recipe-transfers').json()['items']), 1)
            app.state.driver.factory.assert_not_called()
        self.assertEqual(self.validate(entries)['entries'], [dict(valid=True, same=True)] * 4)

    def test_malformed_or_mismatched_receipt_preserves_operation_hint_without_confirmation(self):
        app, client, revision = recipe_transfer_fixture(self)
        app.state.driver.poll()
        response = client.post('/api/recipe-transfers/product/dispatch', json=self.request(app, revision))
        self.assertEqual(response.status_code, 200, response.text)
        original, expected = self.receipt(response), self.expected(revision)
        invalid = [None, {}, {**deepcopy(original), 'ok': False}, {**deepcopy(original), 'transfer': None}]
        for path, value in [(('transaction', 'id'), 2**53), (('transfer', 'transaction', 'sequence'), 100),
            (('transfer', 'transaction', 'operation_id'), 'f' * 32), (('transfer', 'profile_id'), 'different'),
            (('transfer', 'snapshot', 'id'), revision['id'] + 1), (('transfer', 'snapshot', 'version'), revision['version'] + 1),
            (('transaction', 'state'), 'uncertain'), (('transfer', 'envelope', 'sequence'), 100),
            (('transaction', 'operation_id'), '')]:
            data = deepcopy(original)
            parent = data
            for key in path[:-1]: parent = parent[key]
            parent[path[-1]] = value
            invalid.append(data)
        invalid.extend([{**deepcopy(original), 'operation_id': '0' * 32}, {**deepcopy(original), 'audit_status': 'uncertain'}])
        entries = [dict(data=data, expected=expected) for data in invalid]
        result = self.validate(entries)['entries']
        self.assertTrue(all(not item['valid'] and 'Verify transfer history and PLC state before retrying.' in item['message'] for item in result))
        self.assertIn(f"Operation {original['operation_id']}", result[3]['message'])
        self.assertEqual(len(client.get('/api/recipe-transfers').json()['items']), 1)
        self.assertEqual(app.state.driver._tags['CycleCommand']['RequestSequence'], 1)
        app.state.driver.factory.assert_not_called()

    def test_actual_uncertain_write_failure_and_transport_errors_keep_non_replay_guidance(self):
        app, client, revision = recipe_transfer_fixture(self)
        app.state.driver.poll()
        with patch.object(app.state.driver, 'write_command_request', side_effect=OSError('Synthetic commit failure')) as commit:
            response = client.post('/api/recipe-transfers/product/dispatch', json=self.request(app, revision))
            self.assertEqual(response.status_code, 409, response.text)
            commit.assert_called_once()
        self.assertEqual(response.headers['X-OpenHMI-Audit-Status'], 'uncertain')
        problem = dict(message=response.json()['detail'], status=409, operation_id=response.headers['X-OpenHMI-Operation-ID'], audit_status='uncertain')
        errors = [problem, dict(message='Failed to fetch'), dict(message='Unexpected JSON token'),
                  dict(message='Journal unavailable', status=503), dict(message='Sign in first', status=401)]
        messages = self.validate(errors=errors)['messages']
        self.assertIn(problem['operation_id'], messages[0])
        for message in messages[:4]: self.assertIn('verify', message.lower())
        self.assertEqual(messages[-1], 'Sign in first')
        for body in (True, 'null'):
            malformed = frontend('recipe_transfers', malformedResponse=body, dispatches=[dict(profile='product',
                revision=1, version=1, project=2, reason='Synthetic receipt parse failure')])
            self.assertEqual(len(malformed['requests']), 1)
            error = malformed['results'][0]
            self.assertEqual((error['operation_id'], error['audit_status']), ('b' * 32, 'pending'))
            parsed_message = self.validate(errors=[dict(message=error['error'], operation_id=error['operation_id'],
                                                       audit_status=error['audit_status'])])['messages'][0]
            self.assertIn('Verify transfer history and PLC state before retrying.', parsed_message)
            self.assertIn('Operation ' + 'b' * 32, parsed_message)
        history = client.get('/api/recipe-transfers').json()['items']
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['transaction']['state'], 'uncertain')
        app.state.driver.factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
