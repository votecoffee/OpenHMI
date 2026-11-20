"""SQL-backed transfer response parity; seeded states are offline evidence only."""
from copy import deepcopy
import unittest

from tests.test_commands import install
from tests.test_frontend_contract import frontend
from tests.test_recipe_transfer_contract import recipe_transfer_fixture
from openhmi.recipes import canonical, content_hash


STATES = ('prepared', 'staging', 'requested', 'accepted', 'uncertain', 'completed', 'failed', 'interrupted')


class RecipeTransferResponseTests(unittest.TestCase):
    def validate(self, pages=(), records=()):
        return frontend('recipe_transfer_responses', pages=list(pages), records=list(records))

    def fixture(self):
        app, client, revision = recipe_transfer_fixture(self)
        app.state.driver.poll()
        response = client.post('/api/recipe-transfers/product/dispatch', json={
            'revision_id': revision['id'], 'expected_revision_version': revision['version'], 'reason': 'Offline response fixture'})
        self.assertEqual(response.status_code, 200, response.text)
        base = response.json()['transfer']
        # Retain a real captured snapshot/definition, while modeling every durable
        # command state without sending further commands or observing a controller.
        with app.state.store.transaction() as db:
            for sequence, state in enumerate(STATES, 1):
                identifier = base['id']
                result = 0 if state == 'completed' else -7 if state == 'failed' else None
                if sequence > 1:
                    identifier = db.execute('''INSERT INTO command_transaction(operation_id,command_id,channel,signature,
                        definition_json,sequence,state,created_at,updated_at,deadline)
                        SELECT ?,command_id,channel,signature,definition_json,?,?,created_at,updated_at,deadline
                        FROM command_transaction WHERE id=?''', (f'offline-transfer-{sequence}', sequence, state, base['id'])).lastrowid
                    envelope = {**deepcopy(base['envelope']), 'sequence': sequence}
                    db.execute('INSERT INTO recipe_transfer VALUES(?,?,?,?,?,?)', (identifier, base['profile_id'],
                        canonical(base['profile']), canonical(base['snapshot']), canonical(envelope), content_hash(envelope)))
                app.state.commands._update(db, identifier, state, 'Offline response state', result)
        return app, client

    def test_real_pages_all_states_verified_outside_page_and_retired_targets(self):
        app, client = self.fixture()
        pages, records, cursor = [], [], None
        while True:
            response = client.get('/api/recipe-transfers', params={'limit': 2, 'verified_profile': 'product',
                **({'before_id': cursor} if cursor else {})})
            self.assertEqual(response.status_code, 200, response.text)
            page = response.json()
            pages.append(page)
            records.extend(page['items'])
            if not page['has_more']: break
            cursor = page['next_before_id']
        self.assertEqual({item['transaction']['state'] for item in records}, set(STATES))
        self.assertEqual(pages[0]['verified']['transaction']['state'], 'completed')
        self.assertNotIn(pages[0]['verified']['id'], [item['id'] for item in pages[0]['items']])
        # Project apply correctly refuses unresolved commands. Finish only the
        # modeled pending fixture rows before testing renamed/retired targets.
        with app.state.store.transaction() as db:
            for item in records:
                if item['transaction']['state'] in ('prepared', 'staging', 'requested', 'accepted', 'uncertain'):
                    app.state.commands._update(db, item['id'], 'interrupted', 'Offline fixture closed')
        project = client.get('/api/project').json()['active']
        project['recipe_transfers'][0].update(id='renamed', name='Renamed target')
        install(client, project)
        renamed = client.get('/api/recipe-transfers?verified_profile=renamed').json()
        self.assertEqual(renamed['verified_profile'], 'renamed')
        self.assertIsNone(renamed['verified'], 'Renaming changes the target signature; old history is not current verification')
        self.assertTrue(all(item['profile_id'] == 'product' for item in renamed['items']))
        pages.append(renamed)
        project['recipe_transfers'] = []
        install(client, project)
        retired = client.get('/api/recipe-transfers').json()
        self.assertEqual(retired['profiles'], [])
        self.assertTrue(retired['has_history'])
        pages.append(retired)
        empty = client.get('/api/recipe-transfers?profile_id=missing').json()
        self.assertEqual(empty['items'], [])
        self.assertTrue(empty['has_history'])
        pages.append(empty)
        details = []
        for item in records:
            detail = client.get(f"/api/recipe-transfers/{item['id']}")
            self.assertEqual(detail.status_code, 200, detail.text)
            details.append(detail.json())
        valid = self.validate(pages, records + details)
        self.assertEqual(valid, dict(pages=[True] * len(pages), records=[True] * (len(records) + len(details))))
        app.state.driver.factory.assert_not_called()

    def test_consumed_fields_nullable_history_and_incoherent_pages(self):
        _, client = self.fixture()
        page = client.get('/api/recipe-transfers?verified_profile=product').json()
        row = page['items'][0]
        legacy = deepcopy(row)
        for key in ('approved_by', 'transferred_by', 'transfer_reason'): legacy['snapshot'].pop(key, None)
        legacy['snapshot']['content'].pop('image_id', None)
        legacy['snapshot']['content']['parameters'] = None  # Not consumed by this panel.
        legacy['transaction'].update(result_code=None, error=None, events=[], updated_at=None)
        valid_records = [row, legacy]
        invalid_records = [None, {}, {**deepcopy(row), 'profile': None}, {**deepcopy(row), 'snapshot': None}]
        for path, value in [(('snapshot', 'production_approved'), 'false'), (('snapshot', 'number'), 2**53),
            (('snapshot', 'approved_by'), {}), (('snapshot', 'content', 'title'), None),
            (('snapshot', 'content', 'image_id'), 'bad-id'), (('transaction', 'events'), [None]),
            (('transaction', 'updated_at'), {}), (('transaction', 'id'), row['id'] + 1)]:
            item = deepcopy(row)
            parent = item
            for key in path[:-1]: parent = parent[key]
            parent[path[-1]] = value
            invalid_records.append(item)
        def packed(items, more=False, cursor=None):
            return {**deepcopy(page), 'items': items, 'has_more': more, 'next_before_id': cursor}
        maximum = []
        for identifier in range(100, 0, -1):
            item = deepcopy(row)
            item['id'] = item['transaction']['id'] = identifier
            maximum.append(item)
        valid_pages = [page, packed([]), packed([legacy]), packed(maximum),
                       {**packed([]), 'has_history': False, 'profiles': [], 'verified': None}]
        invalid_pages = [None, {}, packed([None]), packed([], True, 1), packed([row], True, row['id'] + 1),
                         packed([row, row]), packed(list(reversed(page['items']))), packed(maximum + [row]),
                         {**deepcopy(page), 'profiles': [page['profiles'][0], page['profiles'][0]]},
                         {**deepcopy(page), 'unresolved_profiles': [None]}, {**deepcopy(page), 'has_history': False}]
        bad_verified = deepcopy(page)
        bad_verified['verified']['transaction']['state'] = 'uncertain'
        invalid_pages.append(bad_verified)
        result = self.validate(valid_pages + invalid_pages, valid_records + invalid_records)
        self.assertEqual(result['pages'], [True] * len(valid_pages) + [False] * len(invalid_pages))
        self.assertEqual(result['records'], [True] * len(valid_records) + [False] * len(invalid_records))


if __name__ == '__main__':
    unittest.main()
