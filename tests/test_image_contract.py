"""Image-library production queries and response validation across JS/Python."""
from types import SimpleNamespace
from unittest.mock import Mock
import unittest
from urllib.parse import parse_qs, urlsplit
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openhmi.canvas_routes import add_canvas_routes
from openhmi.canvas import CanvasImages
from openhmi.projects import ProjectStore
from tests.test_frontend_contract import frontend


class ImageQueryContractTests(unittest.TestCase):
    def router(self):
        images = SimpleNamespace(list=Mock(side_effect=lambda before, limit, search: {
            'before': before, 'limit': limit, 'search': search}))
        security = SimpleNamespace(require=Mock())
        app = FastAPI()
        add_canvas_routes(app, images, security)
        return TestClient(app), images, security

    def test_browser_queries_bind_to_image_router_parameters(self):
        requests = frontend('image_queries')
        self.assertEqual(len(requests), 6)
        client, images, security = self.router()
        with client:
            for request in requests:
                with self.subTest(path=request['path']):
                    self.assertEqual(request.get('method', 'GET'), 'GET')
                    self.assertNotIn('body', request)
                    self.assertEqual(request['headers']['X-OpenHMI-Project'], 'a' * 32)
                    reply = client.get(request['path'], headers=request['headers'])
                    self.assertEqual(reply.status_code, 200, reply.text)
                    query = parse_qs(urlsplit(request['path']).query)
                    self.assertEqual(reply.json(), {
                        'before': int(query['before'][0]) if 'before' in query else None,
                        'limit': int(query.get('limit', ['12'])[0]),
                        'search': query.get('search', [''])[0],
                    })
        self.assertEqual(requests[0]['path'], '/api/canvas-images')
        self.assertEqual(requests[1]['path'], '/api/canvas-images?before=42')
        images.list.assert_any_call(9223372036854775807, 32, '设备 / %.png?#')
        self.assertEqual(security.require.call_count, len(requests))
        self.assertTrue(all(call.args[1] == 'project.edit' for call in security.require.call_args_list))

    def test_invalid_queries_are_rejected_before_service_or_security_calls(self):
        client, images, security = self.router()
        paths = ['/api/canvas-images?before=0', '/api/canvas-images?before=9223372036854775808',
                 '/api/canvas-images?limit=0', '/api/canvas-images?limit=33',
                 '/api/canvas-images?search=' + 'x' * 101]
        with client:
            for path in paths:
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, 422)
        images.list.assert_not_called()
        security.require.assert_not_called()

    def test_real_sql_pages_pass_browser_validator_and_malformed_pages_fail(self):
        store = ProjectStore()
        self.addCleanup(store.close)
        images = CanvasImages(store)
        # Metadata-only rows: this checks listing contracts, not image decoding.
        with store.transaction() as db:
            for code, name in [('a', ''), ('b', '机器 ?#.png'), ('c', 'Third.png')]:
                db.execute('INSERT INTO canvas_image VALUES(?,?,?,?)', (code * 64, 'image/webp', b'fixture', name))
        first = images.list(None, 2)
        second = images.list(first['next_before'], 2)
        search = images.list(None, 12, '机器 ?#')
        empty = images.list(None, 12, 'missing')
        valid = [first, second, search, empty]
        item = {'id': 'a' * 64, 'name': ''}
        invalid = [None, {}, {'items': []}, {'items': [], 'next_before': 1},
                   {'items': [item], 'next_before': '42'}, {'items': [item], 'next_before': True},
                   {'items': [item], 'next_before': 0}, {'items': [item], 'next_before': -1},
                   {'items': [item], 'next_before': 2**53}, {'items': [item], 'next_before': 1.5},
                   {'items': [item, item], 'next_before': None},
                   {'items': [{'id': 'bad', 'name': 'Broken'}], 'next_before': None},
                   {'items': [{'id': 'a' * 64, 'name': None}], 'next_before': None}]
        self.assertEqual(frontend('image_pages', pages=valid + invalid), [True] * len(valid) + [False] * len(invalid))
        self.assertEqual(first['items'][0]['name'], 'Third.png')
        self.assertEqual(second['items'][0]['name'], '')
        self.assertEqual(search['items'][0]['id'], 'b' * 64)


if __name__ == '__main__':
    unittest.main()
