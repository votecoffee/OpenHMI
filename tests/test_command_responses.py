"""Real SQL command response shapes accepted by production browser validators."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openhmi.alarms import utc_now
from openhmi.commands import CommandService
from openhmi.command_routes import add_command_routes
from openhmi.projects import ProjectStore
from tests.test_frontend_contract import frontend


STATES = ('prepared', 'staging', 'requested', 'accepted', 'uncertain', 'completed', 'failed', 'interrupted')


class CommandResponseContractTests(unittest.TestCase):
    def service(self):
        store = ProjectStore()
        self.addCleanup(store.close)
        driver = Mock()
        service = CommandService(store, driver)
        # Persist every state through the same service update path. No dispatch,
        # controller observation, credentials or live transport are involved.
        with store.transaction() as db:
            for sequence, state in enumerate(STATES, 1):
                result = 0 if state == 'completed' else -7 if state == 'failed' else None
                stamp = utc_now()
                cursor = db.execute('''INSERT INTO command_transaction(operation_id,command_id,channel,signature,
                    definition_json,sequence,state,created_at,updated_at,deadline)
                    VALUES(?,?,?,?,?,?,?,?,?,?)''',
                    (f'operation-{sequence}', 'retired_cycle', f'offline-{sequence}', 'fixture', '{}',
                     sequence, state, stamp, stamp, stamp))
                service._update(db, cursor.lastrowid, state, '' if state == 'prepared' else '设备 Δ evidence', result)
        return store, driver, service

    def test_actual_detail_pages_exports_and_restart_rows_match_browser_contract(self):
        store, driver, service = self.service()
        app = FastAPI()
        add_command_routes(app, service, SimpleNamespace(require=Mock()))
        records, pages = [], []
        with TestClient(app) as client:
            page = client.get('/api/commands?limit=3').json()
            while True:
                pages.append(page)
                for item in page['items']:
                    detail = client.get(f"/api/commands/{item['id']}").json()
                    self.assertEqual(detail, item)
                    exported = client.get(f"/api/commands/{item['id']}?download=true")
                    self.assertEqual(exported.json()['transaction'], detail)
                    self.assertEqual(exported.json()['project_id'], store.snapshot()['project_id'])
                    self.assertEqual(exported.headers['cache-control'], 'no-store')
                    self.assertFalse({'signature', 'channel', 'definition_json'} & detail.keys())
                    records.append(detail)
                if not page['has_more']: break
                page = client.get(f"/api/commands?limit=3&before_id={page['next_before_id']}").json()
            pages.extend([service.recent(command_id='missing'), service.recent(state='unresolved'),
                          *[service.recent(state=state) for state in STATES]])
        outcome = frontend('command_responses', records=records, pages=pages)
        self.assertEqual(set(outcome['states']), set(STATES))
        self.assertEqual(outcome['records'], [True] * len(records))
        self.assertEqual(outcome['pages'], [True] * len(pages))
        by_state = {item['state']: item for item in records}
        self.assertIsNone(by_state['prepared']['error'])
        self.assertEqual(by_state['prepared']['events'][0]['detail'], '')
        self.assertIsNone(by_state['uncertain']['result_code'])
        self.assertEqual(by_state['completed']['result_code'], 0)
        self.assertEqual(by_state['failed']['result_code'], -7)
        restarted = CommandService(store, driver)
        restart_page = restarted.recent()
        restart_rows = {row['id']: row for row in restart_page['items']}
        for row in records:
            expected = 'interrupted' if row['state'] == 'prepared' else 'uncertain' if row['state'] in ('staging', 'requested', 'accepted') else row['state']
            self.assertEqual(restart_rows[row['id']]['state'], expected)
        result = frontend('command_responses', records=list(restart_rows.values()), pages=[restart_page])
        self.assertTrue(all(result['records']) and all(result['pages']))
        self.assertEqual(driver.mock_calls, [])

    def test_malformed_records_and_incoherent_pages_are_rejected(self):
        _, _, service = self.service()
        record = service.get(1)
        valid = [record, {**deepcopy(record), 'events': []},
                 {**deepcopy(record), 'sequence': 2147483647, 'id': 2**53 - 1}]
        invalid = [None, {}, *[{**deepcopy(record), key: value} for key, value in (
            ('id', 0), ('id', 2**53), ('sequence', 0), ('sequence', -1),
            ('sequence', 2147483648), ('sequence', True), ('state', 'unknown'),
            ('result_code', {}), ('error', {}), ('events', None),
            ('events', [{'timestamp': None, 'state': 'prepared', 'detail': ''}]),
            ('events', [{'timestamp': 'stamp', 'state': 'unknown', 'detail': ''}]),
            ('events', [{'timestamp': 'stamp', 'state': 'prepared', 'detail': {}}]))]]
        page = service.recent(limit=3)
        second = service.recent(before_id=page['next_before_id'], limit=3)
        malformed = [None, {}, {'items': [], 'has_more': True, 'next_before_id': 1},
            {**deepcopy(page), 'next_before_id': page['items'][0]['id']},
            {**deepcopy(page), 'items': [page['items'][0], page['items'][0]]},
            {**deepcopy(page), 'items': list(reversed(page['items']))},
            {'items': [], 'has_more': False, 'next_before_id': 1},
            {'items': [record], 'has_more': 'yes', 'next_before_id': None}]
        oversized = [{**deepcopy(record), 'id': identifier} for identifier in range(201, 0, -1)]
        malformed.append({'items': oversized, 'has_more': False, 'next_before_id': None})
        result = frontend('command_responses', records=valid + invalid, pages=[page, second] + malformed)
        self.assertEqual(result['records'], [True] * len(valid) + [False] * len(invalid))
        self.assertEqual(result['pages'], [True, True] + [False] * len(malformed))


if __name__ == '__main__':
    unittest.main()
