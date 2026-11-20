"""Shelving-list browser URLs and guards match the real SQL-backed registrar."""
from copy import deepcopy
import unittest
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openhmi.activity import ActivityJournal
from openhmi.alarm_routes import add_alarm_routes
from openhmi.alarms import AlarmMonitor
from openhmi.project_models import Project, SaveRequest, RevisionRequest
from openhmi.projects import ProjectStore
from openhmi.security import Security
from tests.test_frontend_contract import frontend
from tests.test_security import FakeWindows


class AlarmShelfContractTests(unittest.TestCase):
    def setUp(self):
        self.store = ProjectStore()
        self.addCleanup(self.store.close)
        project = Project.model_validate(self.store.snapshot()['active'])
        definition = project.alarms[0]
        self.ids = ['A_alarm', 'a_alarm', 'm' * 100, 'z_alarm']
        project.alarms = [definition.model_copy(update={'id': identifier, 'message': '设备 ' + identifier})
                          for identifier in reversed(self.ids)]
        saved = self.store.save(SaveRequest(expected_revision=1, project=project))
        self.store.apply(RevisionRequest(expected_revision=saved['draft_revision']))
        self.source = Mock(return_value={'ProcessAlarm': True})
        self.monitor = AlarmMonitor(self.store, self.source)
        self.monitor.sample()
        for index, item in enumerate(self.monitor.snapshot()['outstanding'], 1):
            self.monitor.shelves.begin(item['occurrence_id'], 3600, '设备\nReview, +%',
                                      ('Fixture operator', 'local'), f'{index:032x}')
        self.driver = Mock(spec=['sample_snapshot'])
        self.security = Security(self.store, windows=FakeWindows())
        self.activity = ActivityJournal(self.store, self.security)
        app = FastAPI()
        add_alarm_routes(app, self.monitor, self.security, self.activity, self.driver, self.store)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.monitor.shelves.active = Mock(wraps=self.monitor.shelves.active)

    def browser(self, queries=(), pages=()):
        return frontend('alarm_shelves', queries=list(queries), pages=list(pages))

    def read(self, query=None):
        path = self.browser([query or {}])['paths'][0]
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def assert_no_acquisition(self):
        self.source.assert_called_once_with()
        self.driver.sample_snapshot.assert_not_called()

    def test_generated_cursors_page_in_server_order_and_restore_maximum_model_id(self):
        self.assertEqual(self.browser([{}])['paths'], ['/api/alarms/shelves?after_id='])
        pages, after = [], ''
        while True:
            page = self.read(dict(after=after, options={'limit': 1}))
            pages.append(page)
            if not page['has_more']: break
            after = page['next_after_id']
        self.assertEqual([page['items'][0]['alarm_id'] for page in pages], self.ids)
        self.assertEqual(pages[2]['next_after_id'], 'm' * 100)
        self.assertEqual(self.browser(pages=pages)['valid'], [True] * 4)
        self.assertEqual(len(self.read()['items']), 4)
        self.assertEqual(len(self.read(dict(options={'limit': 200}))['items']), 4)
        self.assertEqual(self.read(dict(after='z_alarm'))['items'], [])
        item = pages[2]['items'][0]
        self.assertEqual(item['reason'], '设备\nReview, +%')
        restore = frontend('alarm_mutations', mutations=[dict(action='restore', id=item['alarm_id'],
                           expected=item['operation_id'], reason='Offline review')])['requests'][0]
        response = self.client.post(restore['path'], json=restore['body'])
        self.assertEqual(response.status_code, 200, response.text)
        remaining = self.read()
        self.assertEqual([row['alarm_id'] for row in remaining['items']], ['A_alarm', 'a_alarm', 'z_alarm'])
        self.assertEqual(self.browser(pages=[remaining])['valid'], [True])
        self.assert_no_acquisition()

    def test_query_encoding_and_invalid_bounds_precede_shelf_reads(self):
        special = self.browser([dict(after='设备 A,+%?&#')])['paths'][0]
        self.assertEqual(special, '/api/alarms/shelves?after_id=%E8%AE%BE%E5%A4%87%20A%2C%2B%25%3F%26%23')
        queries = [dict(options={'limit': value}) for value in (0, 201, 1.5, 'bad')]
        queries.append(dict(after='x' * 101))
        for path in self.browser(queries)['paths']:
            with self.subTest(path=path): self.assertEqual(self.client.get(path).status_code, 422)
        self.monitor.shelves.active.assert_not_called()
        self.assertEqual(self.activity.query()['items'], [])
        self.assertEqual(self.client.get(special).status_code, 200)
        self.assert_no_acquisition()

    def test_response_guards_preserve_row_compatibility_and_reject_incoherent_pages(self):
        page = self.read()
        row = page['items'][0]
        def pack(items, more=False, cursor=None):
            return dict(items=items, has_more=more, next_after_id=cursor)
        legacy = deepcopy(row)
        legacy['definition']['messages'] = None
        # Additional retained fields and legacy operation tokens stay readable.
        legacy['operation_id'] = 'legacy-token'
        legacy['extra'] = {'retained': True}
        maximum = [{**deepcopy(row), 'alarm_id': f'alarm_{index:03}'} for index in range(200)]
        valid = [page, pack([]), pack([row], True, row['alarm_id']), pack([legacy]), pack(maximum)]
        invalid = [None, {}, pack([None]), pack([], True, 'cursor'), pack([row], True, 'wrong'),
                   pack([row], False, row['alarm_id']), pack([row, row]), pack(list(reversed(page['items']))),
                   pack(maximum + [{**deepcopy(row), 'alarm_id': 'alarm_200'}]),
                   {**pack([]), 'has_more': 0}]
        for field, value in (('alarm_id', ''), ('actor', None), ('provider', 3), ('reason', []),
                             ('operation_id', ''), ('expires_at', 'invalid'), ('definition', None)):
            invalid.append(pack([{**deepcopy(row), field: value}]))
        bad_translation = deepcopy(row)
        bad_translation['definition']['messages'] = {'en': None}
        invalid.append(pack([bad_translation]))
        self.assertEqual(self.browser(pages=valid + invalid)['valid'], [True] * len(valid) + [False] * len(invalid))
        self.assert_no_acquisition()


if __name__ == '__main__':
    unittest.main()
