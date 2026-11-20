"""Actual browser command queries bound through the focused FastAPI router."""
from types import SimpleNamespace
from typing import get_args
from unittest.mock import Mock
import unittest
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openhmi.command_contracts import CommandHistoryState
from openhmi.command_routes import add_command_routes
from tests.test_frontend_contract import frontend


class CommandQueryContractTests(unittest.TestCase):
    def router(self):
        service = SimpleNamespace(
            recent=Mock(side_effect=lambda limit, before, command, state: {
                'limit': limit, 'before_id': before, 'command_id': command, 'state': state}),
            get=Mock(side_effect=lambda identifier: {'id': identifier}),
            store=SimpleNamespace(snapshot=lambda: {'project_id': 'offline-contract'}),
        )
        security = SimpleNamespace(require=Mock())
        app = FastAPI()
        add_command_routes(app, service, security)
        return TestClient(app), service, security

    def test_browser_filters_ids_and_export_bind_to_the_router_contract(self):
        payload = frontend('command_queries')
        self.assertEqual(set(payload['states']), set(get_args(CommandHistoryState)))
        requests = payload['requests']
        self.assertEqual(len(requests), len(payload['states']) + 4)
        client, service, security = self.router()
        with client:
            for request in requests:
                with self.subTest(path=request['path']):
                    self.assertEqual(request.get('method', 'GET'), 'GET')
                    self.assertNotIn('body', request)
                    self.assertEqual(request['headers']['X-OpenHMI-Project'], 'a' * 32)
                    reply = client.get(request['path'], headers=request['headers'])
                    self.assertEqual(reply.status_code, 200, reply.text)
                    url = urlsplit(request['path'])
                    query = parse_qs(url.query)
                    if url.path == '/api/commands':
                        self.assertEqual(reply.json(), {
                            'limit': int(query.get('limit', ['100'])[0]),
                            'before_id': int(query['before_id'][0]) if 'before_id' in query else None,
                            'command_id': query.get('command_id', [''])[0],
                            'state': query.get('state', [''])[0],
                        })
                    elif query.get('download') == ['true']:
                        self.assertEqual(reply.json()['transaction']['id'], 9223372036854775807)
                        self.assertEqual(reply.json()['format'], 'openhmi.command-transaction')
                        self.assertEqual(reply.json()['project_id'], 'offline-contract')
                        self.assertEqual(reply.headers['cache-control'], 'no-store')
                        self.assertIn('openhmi-command-9223372036854775807.json', reply.headers['content-disposition'])
                    else:
                        self.assertEqual(reply.json(), {'id': 123})
        self.assertEqual(parse_qs(urlsplit(requests[0]['path']).query), {'command_id': ['设备 / Cycle?#'], 'limit': ['1']})
        self.assertEqual(requests[1]['path'], '/api/commands?limit=50')
        service.recent.assert_any_call(200, 9223372036854775807, '设备 / Cycle?#', 'unresolved')
        self.assertEqual(security.require.call_count, len(requests))
        for call in security.require.call_args_list:
            self.assertEqual(call.args[1], 'runtime.operate')

    def test_out_of_contract_queries_are_rejected_before_service_calls(self):
        client, service, security = self.router()
        paths = [
            '/api/commands?limit=0', '/api/commands?limit=201',
            '/api/commands?before_id=0', '/api/commands?before_id=9223372036854775808',
            '/api/commands?command_id=' + 'x' * 61, '/api/commands?state=unknown',
            '/api/commands/0', '/api/commands/9223372036854775808',
        ]
        with client:
            for path in paths:
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, 422)
        service.recent.assert_not_called()
        service.get.assert_not_called()
        security.require.assert_not_called()


if __name__ == '__main__':
    unittest.main()
